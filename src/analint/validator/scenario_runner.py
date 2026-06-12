from __future__ import annotations

import copy
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Set, Subtract
from analint.models.flow import Assert, Emitted
from analint.models.predicate import Predicate
from analint.models.root import Spec
from analint.models.scenario import Expect, Scenario
from analint.models.scope import (
    context_key_label,
    field_context_key,
    instance_context_key,
    is_field_ref,
)
from analint.reporter.base import Finding, ScenarioResult, Severity
from analint.validator.rule_checker import evaluate, resolve
from analint.validator.structural import _collect_field_refs, _describe


def run_scenario(scenario: Scenario, spec: Spec) -> ScenarioResult:
    findings: list[Finding] = []
    context = {instance_context_key(inst): inst for inst in scenario.given}
    action = scenario.action

    relevant_invariants = [
        inv for inv in spec.invariants if _referenced_keys(inv.expression) <= set(context)
    ]
    checks_count = len(relevant_invariants) + len(action.pre) + len(action.post)

    # Phase 1: world invariants and preconditions against the pre-state
    for inv in relevant_invariants:
        _check(
            findings,
            inv.expression,
            context,
            "INVARIANT",
            inv.label or _describe(inv.expression),
            f"invariant:{inv.id}",
        )
    for pred in action.pre:
        _check(findings, pred, context, "PRE", _describe(pred), f"action:{action.id}")

    _check_terminal_states(findings, scenario, spec, context)

    # Pre-execution rejection is the only thing Expect.FAIL may legitimise;
    # anything that breaks after the effects ran is a model defect (research/14 §7.3)
    pre_errors = any(f.severity == Severity.ERROR for f in findings)
    post_findings: list[Finding] = []

    # Phase 2: effects — simultaneous facts about the next state
    if not pre_errors:
        try:
            post_context = _apply_effects(action.effect, context)
        except Exception as exc:
            post_findings.append(
                Finding(Severity.ERROR, f"action:{action.id}", f"effect evaluation error: {exc}")
            )
            post_context = context
    else:
        post_context = context

    if not pre_errors and not post_findings:
        # Phase 3: postconditions, invariants, and field constraints (post-state)
        _check_field_constraints(post_findings, action, post_context)
        for pred in action.post:
            _check(
                post_findings, pred, post_context, "POST", _describe(pred), f"action:{action.id}"
            )
        for inv in relevant_invariants:
            _check(
                post_findings,
                inv.expression,
                post_context,
                "INVARIANT (post)",
                inv.label or _describe(inv.expression),
                f"invariant:{inv.id}",
            )

        # Phase 4: then assertions (Assert / Emitted)
        emitted_names = {(e if isinstance(e, type) else type(e)).__name__ for e in action.emits}
        for assertion in scenario.then:
            if isinstance(assertion, Assert):
                try:
                    if not evaluate(assertion.predicate, post_context):
                        post_findings.append(
                            Finding(
                                Severity.ERROR,
                                f"scenario:{scenario.id}",
                                f"then: {_describe(assertion.predicate)} — not satisfied",
                            )
                        )
                except Exception as exc:
                    post_findings.append(
                        Finding(
                            Severity.ERROR,
                            f"scenario:{scenario.id}",
                            f"then evaluation error: {exc}",
                        )
                    )
            elif isinstance(assertion, Emitted):
                if assertion.event_cls.__name__ not in emitted_names:
                    post_findings.append(
                        Finding(
                            Severity.ERROR,
                            f"scenario:{scenario.id}",
                            f"then: event '{assertion.event_cls.__name__}' not in action.emits",
                        )
                    )
            else:
                post_findings.append(
                    Finding(
                        Severity.ERROR,
                        f"scenario:{scenario.id}",
                        f"then entry '{assertion!r}' is not Assert(...) or Emitted(...)",
                    )
                )

    post_errors = any(f.severity == Severity.ERROR for f in post_findings)
    findings.extend(post_findings)

    if scenario.expected == Expect.FAIL:
        # passes only when the action was rejected BEFORE its effects ran
        passed = pre_errors
        if passed:
            findings.append(
                Finding(
                    Severity.INFO,
                    f"scenario:{scenario.id}",
                    "correctly blocked — rules rejected this data as expected",
                )
            )
        else:
            message = "expected the action to be blocked, but every precondition passed"
            if post_errors:
                message += " — the post-state failures above are a model defect, not a rejection"
            findings.append(Finding(Severity.ERROR, f"scenario:{scenario.id}", message))
    else:
        passed = not (pre_errors or post_errors)

    return ScenarioResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        passed=passed,
        findings=findings,
        rules_count=checks_count,
    )


def _check(
    findings: list[Finding],
    pred: Predicate,
    context: dict,
    label: str,
    text: str,
    loc: str,
) -> None:
    try:
        if not evaluate(pred, context):
            findings.append(Finding(Severity.ERROR, loc, f"{label} failed: {text}"))
    except Exception as exc:
        findings.append(Finding(Severity.ERROR, loc, f"evaluation error: {exc}"))


def _referenced_keys(pred: Predicate) -> set[Any]:
    return {field_context_key(ref) for ref in _collect_field_refs(pred)}


def _check_field_constraints(findings: list, action: Action, post: dict) -> None:
    """Effects must not drive a field outside its declared Field(...) range
    (saturating fields clamp instead)."""
    from analint.models.entity import all_fields

    for effect in action.effect:
        if not isinstance(effect, (Set, Subtract, Add)):
            continue
        cls = effect.field.entity_cls
        key = field_context_key(effect.field)
        inst = post.get(key)
        if inst is None:
            continue
        desc = all_fields(cls).get(effect.field.field_name)
        if desc is None or desc.spec is None or not desc.spec.has_constraints():
            continue
        value = inst.__dict__.get(effect.field.field_name)
        problem = desc.spec.violation(value)
        if problem is None:
            continue
        if desc.spec.saturate:
            inst.__dict__[effect.field.field_name] = desc.spec.clamp(value)
            continue
        findings.append(
            Finding(
                Severity.ERROR,
                f"action:{action.id}",
                f"field constraint violated: {cls.__name__}.{effect.field.field_name} {problem}",
            )
        )


def _check_terminal_states(findings: list, scenario: Scenario, spec: Spec, context: dict) -> None:
    """An entity whose lifecycle field is in a terminal state cannot be modified."""
    touched = {
        field_context_key(e.field)
        for e in scenario.action.effect
        if isinstance(e, (Set, Subtract, Add)) and is_field_ref(e.field)
    }
    for lc in spec.lifecycles:
        if not lc.terminal:
            continue
        for key in touched:
            if _key_entity_cls(key) is not lc.entity_cls:
                continue
            inst = context.get(key)
            if inst is None:
                continue
            value = getattr(inst, lc.field_name, None)
            if value in lc.terminal:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        f"lifecycle:{lc.id}",
                        f"{context_key_label(key)}.{lc.field_name}={value!r} is terminal — "
                        f"the entity cannot be modified",
                    )
                )


def _apply_effects(effects: list, context: dict) -> dict:
    """Return a new context with entity copies modified by effects.

    Effects are simultaneous facts about the next state: every right-hand side
    is resolved against the pre-state, so the order of the list carries no
    meaning and effects never observe each other.
    """
    updates: list[tuple[Any, str, Any]] = []
    for effect in effects:
        target = field_context_key(effect.field) if is_field_ref(effect.field) else None
        if isinstance(effect, (Set, Subtract, Add)) and target not in context:
            continue  # target entity absent from given — structural validation warns about this
        if isinstance(effect, Set):
            updates.append((target, effect.field.field_name, resolve(effect.value, context)))
        elif isinstance(effect, Subtract):
            current = resolve(effect.field, context)
            updates.append(
                (
                    target,
                    effect.field.field_name,
                    current - resolve(effect.amount, context),
                )
            )
        elif isinstance(effect, Add):
            current = resolve(effect.field, context)
            updates.append(
                (
                    target,
                    effect.field.field_name,
                    current + resolve(effect.amount, context),
                )
            )

    post = {cls: copy.copy(inst) for cls, inst in context.items()}
    for key, field_name, value in updates:
        entity = post.get(key)
        if entity is not None:
            entity.__dict__[field_name] = value
    return post


def _key_entity_cls(key: Any) -> type:
    return key.entity_cls if hasattr(key, "entity_cls") else key
