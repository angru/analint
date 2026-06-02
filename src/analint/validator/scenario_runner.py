from __future__ import annotations
import copy
from analint.models.business import RuleType
from analint.models.effect import Set, Subtract, Add
from analint.models.flow import Assert, Emitted
from analint.models.root import Spec
from analint.models.scenario import Expect, Scenario
from analint.reporter.base import Finding, ScenarioResult, Severity
from analint.validator.rule_checker import evaluate, resolve
from analint.validator.structural import _describe


def run_scenario(scenario: Scenario, spec: Spec) -> ScenarioResult:
    findings: list[Finding] = []
    context = {type(inst): inst for inst in scenario.given}

    uc = scenario.use_case

    # Phase 1: Invariants and Preconditions
    for rule in uc.rules:
        if rule.expression is None:
            continue
        if rule.rule_type == RuleType.POSTCONDITION:
            continue
        label = "INVARIANT" if rule.rule_type == RuleType.INVARIANT else "PRECONDITION"
        try:
            if not evaluate(rule.expression, context):
                findings.append(Finding(
                    Severity.ERROR,
                    f"rule:{rule.id}",
                    f"{label} '{rule.name}' failed: {_describe(rule.expression)}",
                ))
        except Exception as exc:
            findings.append(Finding(Severity.ERROR, f"rule:{rule.id}", f"evaluation error: {exc}"))

    # Phase 2: Apply effects (only when no precondition errors)
    pre_errors = any(f.severity == Severity.ERROR for f in findings)
    post_context = _apply_effects(uc.effects, context) if not pre_errors else context

    # Phase 3: Postconditions (against post-state)
    if not pre_errors:
        for rule in uc.rules:
            if rule.expression is None or rule.rule_type != RuleType.POSTCONDITION:
                continue
            try:
                if not evaluate(rule.expression, post_context):
                    findings.append(Finding(
                        Severity.ERROR,
                        f"rule:{rule.id}",
                        f"POSTCONDITION '{rule.name}' failed: {_describe(rule.expression)}",
                    ))
            except Exception as exc:
                findings.append(Finding(Severity.ERROR, f"rule:{rule.id}", f"evaluation error: {exc}"))

    # Phase 4: Then assertions (Assert / Emitted)
    if not pre_errors:
        emitted_names = {e.__name__ for e in uc.emits}
        for assertion in scenario.then:
            if isinstance(assertion, Assert):
                try:
                    if not evaluate(assertion.predicate, post_context):
                        findings.append(Finding(
                            Severity.ERROR,
                            f"scenario:{scenario.id}",
                            f"then: {_describe(assertion.predicate)} — not satisfied",
                        ))
                except Exception as exc:
                    findings.append(Finding(
                        Severity.ERROR,
                        f"scenario:{scenario.id}",
                        f"then evaluation error: {exc}",
                    ))
            elif isinstance(assertion, Emitted):
                if assertion.event_cls.__name__ not in emitted_names:
                    findings.append(Finding(
                        Severity.ERROR,
                        f"scenario:{scenario.id}",
                        f"then: event '{assertion.event_cls.__name__}' not in use_case.emits",
                    ))

    has_errors = any(f.severity == Severity.ERROR for f in findings)
    passed = not has_errors

    if scenario.expected == Expect.FAIL:
        passed = not passed
        if passed:
            findings.append(Finding(
                Severity.INFO,
                f"scenario:{scenario.id}",
                "correctly blocked — rules rejected this data as expected",
            ))

    return ScenarioResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        passed=passed,
        findings=findings,
        rules_count=len(uc.rules),
    )


def _apply_effects(effects: list, context: dict) -> dict:
    """Return a new context with entity copies modified by effects."""
    post = {cls: copy.copy(inst) for cls, inst in context.items()}
    for effect in effects:
        if isinstance(effect, Set):
            entity = post.get(effect.field.entity_cls)
            if entity is not None:
                entity.__dict__[effect.field.field_name] = resolve(effect.value, post)
        elif isinstance(effect, Subtract):
            entity = post.get(effect.field.entity_cls)
            if entity is not None:
                amount = resolve(effect.amount, post)
                entity.__dict__[effect.field.field_name] -= amount
        elif isinstance(effect, Add):
            entity = post.get(effect.field.entity_cls)
            if entity is not None:
                amount = resolve(effect.amount, post)
                entity.__dict__[effect.field.field_name] += amount
    return post
