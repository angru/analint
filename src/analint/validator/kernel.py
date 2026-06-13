"""The transition kernel: one ``step`` shared by scenario, explorer and Flow.

A *transition* answers a single question: can ``action`` fire from ``context``,
and if so, what is the next state? It deliberately does **not** decide whether a
*state* is legal — invariants are a state predicate, applied by each caller at
the state level (root/successor in the explorer, pre/post in a scenario).

Outcome semantics (research/18, research/20; gated by
``tests/test_transition_conformance.py``):

- ``REJECTED`` — a guard blocked the action *before any effect ran*: a false
  precondition, a presence guard (create-present / delete-absent /
  modify-absent), or a terminal-state lock. This is the only outcome a scenario
  ``Expect.FAIL`` may legitimise. The reason is attached as a finding so a
  scenario can explain the block; the explorer ignores it (the action is simply
  disabled and contributes no edge).
- ``DEFECT`` — the model could not evaluate the transition or produced an
  illegal one: an evaluation error in pre/effect/post, a hard ``Field`` range
  violation, an undeclared lifecycle transition, or a false postcondition.
  Never a legitimate rejection.
- ``ACCEPTED`` — a legal transition with a materialised ``post_context``.

Ordering: pre guards → presence/terminal guards → effects → ``Field``
clamp/constraints → lifecycle transition → post → emitted payload
materialisation. ``post_context`` is populated only when the candidate next
state was fully materialised (effects, Field, lifecycle, post and emissions all
passed); the explorer keys its graph decisions off that. Emission is the last
transition phase: an unmaterialisable payload is a transition DEFECT with no
candidate state, so — unlike a state-level invariant violation — it leaves no
witness edge (review 535ecb8).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Create, Delete, Set, Subtract
from analint.models.entity import all_fields
from analint.models.lifecycle import Lifecycle
from analint.models.root import Spec
from analint.models.scope import (
    Absent,
    InstanceRef,
    context_key_label,
    field_context_key,
    is_field_ref,
    is_present,
    present_snapshot,
)
from analint.reporter.base import Finding, Severity
from analint.validator.rule_checker import evaluate, resolve
from analint.validator.structural import _collect_field_refs, _describe


class Outcome(Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFECT = "defect"


@dataclass
class TransitionResult:
    """The result of evaluating one (action, context) transition.

    ``post_context`` is the materialised candidate next state, present whenever
    the effects, field constraints, lifecycle transition and postconditions all
    succeeded — including the post-state-invariant DEFECT case, where a caller
    may keep it as a counterexample witness but must not expand from it.
    """

    outcome: Outcome
    post_context: dict | None = None
    findings: list[Finding] = dc_field(default_factory=list)
    emitted: list = dc_field(default_factory=list)
    changed_fields: dict = dc_field(default_factory=dict)
    # whether the action passed every pre/presence/terminal guard and began to
    # execute — true for ACCEPTED and for any defect raised after the guards
    # (effect/field/lifecycle/post), false for REJECTED and pre-evaluation errors
    entered: bool = False


def _trace_str(steps: list[str]) -> str:
    return " → ".join(steps) if steps else "(initial state)"


def _at(trace: list[str] | None) -> str:
    """Trace suffix naming the pre-state (a precondition is read there)."""
    return f" [at: {_trace_str(trace)}]" if trace is not None else ""


def _after(action: Action, trace: list[str] | None) -> str:
    """Trace suffix naming the state reached by firing the action."""
    return f" [after: {_trace_str([*trace, action.id])}]" if trace is not None else ""


def step(
    spec: Spec,
    action: Action,
    context: dict,
    *,
    trace: list[str] | None = None,
) -> TransitionResult:
    """Evaluate one transition. See module docstring for outcome semantics.

    ``trace`` is the action-id path that reached ``context``; when given, defect
    findings are decorated with it so a counterexample reads end-to-end. Pass
    ``None`` (the default) for a single, context-free transition.
    """
    lifecycles = list(spec.lifecycles)

    # ── pre guards: a false/absent precondition rejects; an error is a defect ──
    for pred in action.pre:
        refs = _collect_field_refs(pred)
        if any(field_context_key(r) not in context for r in refs):
            # the predicate reads an entity intentionally absent from this state
            return _rejected(action, f"PRE not applicable: {_describe(pred)}")
        try:
            if not evaluate(pred, context):
                return _rejected(action, f"PRE failed: {_describe(pred)}")
        except Exception as exc:
            return _defect(
                action,
                f"pre evaluation error: {exc} (predicate: {_describe(pred)}){_at(trace)}",
            )

    # ── presence guards (Set/Add/Subtract target, Create, Delete) ─────────────
    touched = {
        field_context_key(e.field)
        for e in action.effect
        if isinstance(e, (Set, Subtract, Add)) and is_field_ref(e.field)
    }
    for target in touched:
        if isinstance(target, InstanceRef) and not is_present(context, target):
            return _rejected(
                action, f"cannot modify absent entity {target!r} with Set/Add/Subtract"
            )
    for effect in action.effect:
        if isinstance(effect, Create) and is_present(context, effect.target):
            return _rejected(action, f"cannot create already-present entity {effect.target!r}")
        if isinstance(effect, Delete) and not is_present(context, effect.target):
            return _rejected(action, f"cannot delete absent entity {effect.target!r}")

    # ── terminal-state lock: an entity in a terminal lifecycle state is frozen,
    # against field changes and against deletion alike (a Create targets an
    # absent slot, which has no terminal state, so it is exempt) ──────────────
    frozen_targets = touched | {
        effect.target for effect in action.effect if isinstance(effect, Delete)
    }
    for lc in lifecycles:
        if not lc.terminal:
            continue
        for target in frozen_targets:
            if _key_entity_cls(target) is not lc.entity_cls:
                continue
            inst = context.get(target)
            if inst is not None and getattr(inst, lc.field_name, None) in lc.terminal:
                return TransitionResult(
                    Outcome.REJECTED,
                    findings=[
                        Finding(
                            Severity.ERROR,
                            f"lifecycle:{lc.id}",
                            f"{context_key_label(target)}.{lc.field_name}="
                            f"{getattr(inst, lc.field_name)!r} is terminal — "
                            f"the entity cannot be modified or deleted",
                        )
                    ],
                )

    # Past the guards: the action executes, so every outcome from here counts as
    # having entered, whether it accepts or turns out to be a defect.

    # ── effects: simultaneous facts about the next state (effectless: unchanged) ─
    if not action.effect:
        post = context
    else:
        try:
            post = _apply_effects(action.effect, context)
        except Exception as exc:
            return _entered(
                _defect(action, f"effect evaluation error: {exc}{_after(action, trace)}")
            )
        # ── Field clamp / hard constraints, then lifecycle ────────────────────
        field_defect = _check_field_constraints(action, post, trace)
        if field_defect is not None:
            return _entered(field_defect)
        lifecycle_defect = _check_lifecycle_transitions(action, context, post, lifecycles, trace)
        if lifecycle_defect is not None:
            return _entered(lifecycle_defect)

    # ── post (an effectless action still asserts it over the unchanged state) ──
    post_defect = _check_post(action, post, trace)
    if post_defect is not None:
        return _entered(post_defect)

    # ── emitted payload materialisation: the final phase ──────────────────────
    emitted, emit_defect = _materialize_emitted(action, post, trace)
    if emit_defect is not None:
        return _entered(emit_defect)

    return TransitionResult(
        Outcome.ACCEPTED,
        post_context=post,
        emitted=emitted,
        changed_fields=_state_diff(context, post),
        entered=True,
    )


def _rejected(action: Action, message: str) -> TransitionResult:
    return TransitionResult(
        Outcome.REJECTED,
        findings=[Finding(Severity.ERROR, f"action:{action.id}", message)],
    )


def _defect(action: Action, message: str) -> TransitionResult:
    return TransitionResult(
        Outcome.DEFECT,
        findings=[Finding(Severity.ERROR, f"action:{action.id}", message)],
    )


def _entered(result: TransitionResult) -> TransitionResult:
    result.entered = True
    return result


def _apply_effects(effects: list, context: dict) -> dict:
    """Return a new context with entity copies modified by the effects.

    Effects are simultaneous facts about the next state: every right-hand side
    is resolved against the pre-state, so the order of the list carries no
    meaning and effects never observe each other.
    """
    updates: list[tuple[Any, str, Any]] = []
    for effect in effects:
        if not isinstance(effect, (Set, Subtract, Add)):
            continue
        target = field_context_key(effect.field) if is_field_ref(effect.field) else None
        if target not in context:
            continue  # target entity absent from given — structural validation warns
        if isinstance(effect, Set):
            updates.append((target, effect.field.field_name, resolve(effect.value, context)))
        elif isinstance(effect, Subtract):
            current = resolve(effect.field, context)
            updates.append(
                (target, effect.field.field_name, current - resolve(effect.amount, context))
            )
        elif isinstance(effect, Add):
            current = resolve(effect.field, context)
            updates.append(
                (target, effect.field.field_name, current + resolve(effect.amount, context))
            )

    post = {cls: copy.copy(inst) for cls, inst in context.items()}
    for key, field_name, value in updates:
        entity = post.get(key)
        if entity is not None:
            entity.__dict__[field_name] = value
    for effect in effects:
        if isinstance(effect, Create):
            resolved = {name: resolve(value, context) for name, value in effect.fields.items()}
            post[effect.target] = present_snapshot(effect.target, resolved)
        elif isinstance(effect, Delete):
            post[effect.target] = Absent(effect.target)
    return post


def _check_field_constraints(
    action: Action, post: dict, trace: list[str] | None
) -> TransitionResult | None:
    """Effects must not drive a field outside its declared ``Field`` range;
    saturating fields clamp in place instead of failing."""
    for effect in action.effect:
        if isinstance(effect, Create):
            inst = post.get(effect.target)
            if inst is None:
                continue
            for fname, desc in all_fields(effect.target.entity_cls).items():
                if desc.spec is None or not desc.spec.has_constraints():
                    continue
                value = inst.__dict__.get(fname)
                problem = desc.spec.violation(value)
                if problem is None:
                    continue
                if desc.spec.saturate:
                    inst.__dict__[fname] = desc.spec.clamp(value)
                    continue
                return _defect(
                    action,
                    f"field constraint violated: created {effect.target!r}.{fname} "
                    f"{problem}{_after(action, trace)}",
                )
            continue
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
        return _defect(
            action,
            f"field constraint violated: {context_key_label(key)}."
            f"{effect.field.field_name} {problem}{_after(action, trace)}",
        )
    return None


def _check_lifecycle_transitions(
    action: Action,
    ctx: dict,
    post: dict,
    lifecycles: list[Lifecycle],
    trace: list[str] | None,
) -> TransitionResult | None:
    """A change to a lifecycle field must follow a declared transition."""
    for lc in lifecycles:
        for context_key, inst_pre in ctx.items():
            if type(inst_pre) is not lc.entity_cls:
                continue
            inst_post = post.get(context_key)
            if inst_post is None:
                continue
            # a created/deleted slot's lifecycle field is an initial assignment
            # or a teardown, not a declared transition
            if not is_present(ctx, context_key) or not is_present(post, context_key):
                continue
            old = getattr(inst_pre, lc.field_name, None)
            new = getattr(inst_post, lc.field_name, None)
            if old == new:
                continue
            allowed: set = set()
            for t in lc.transitions:
                if t.from_state == old:
                    allowed.update(t.to_states)
            if new not in allowed:
                return _defect(
                    action,
                    f"{context_key_label(context_key)}.{lc.field_name} "
                    f"{_value_str(old)} → {_value_str(new)}, not declared in "
                    f"lifecycle '{lc.id}'{_after(action, trace)}",
                )
    return None


def _check_post(action: Action, post: dict, trace: list[str] | None) -> TransitionResult | None:
    """An action whose declared ``post`` is false (or unevaluable) after its
    effects is a model defect, not a silent edge (research/18 §2.1)."""
    for pred in action.post:
        refs = _collect_field_refs(pred)
        if any(field_context_key(r) not in post for r in refs):
            continue  # references an entity absent from this state — not applicable
        try:
            ok = evaluate(pred, post)
        except Exception as exc:
            return _defect(
                action,
                f"post evaluation error: {exc} (predicate: {_describe(pred)})"
                f"{_after(action, trace)}",
            )
        if not ok:
            return _defect(
                action,
                f"violates its postcondition {_describe(pred)}{_after(action, trace)}",
            )
    return None


def _materialize_emitted(
    action: Action, post: dict, trace: list[str] | None
) -> tuple[list, TransitionResult | None]:
    """Resolve each emitted event's payload templates against the next state.

    A bare ``Event`` class carries no payload and passes through unchanged. An
    ``Event`` instance whose field templates cannot be resolved (a type error, a
    reference to an absent entity) is a model defect, not a silent emission."""
    materialized: list = []
    for event in action.emits:
        if isinstance(event, type):
            materialized.append(event)
            continue
        cls = type(event)
        try:
            values = {fname: resolve(event.__dict__.get(fname), post) for fname in all_fields(cls)}
        except Exception as exc:
            return [], _defect(
                action,
                f"emitted payload evaluation error: {exc} "
                f"(event: {cls.__name__}){_after(action, trace)}",
            )
        materialized.append(cls(**values))
    return materialized, None


def _state_diff(pre: dict, post: dict) -> dict:
    """Per-key map of what changed: field ``(old, new)`` pairs and presence
    flips. The minimal observable state delta a caller can render or assert on."""
    diff: dict[Any, dict[str, Any]] = {}
    for key in post:
        before = pre.get(key)
        after = post[key]
        pre_present = is_present(pre, key) if before is not None else False
        post_present = is_present(post, key)
        changes: dict[str, Any] = {}
        if pre_present != post_present:
            changes["@present"] = (pre_present, post_present)
        if pre_present and post_present:
            for fname in all_fields(type(after)):
                old = before.__dict__.get(fname)
                new = after.__dict__.get(fname)
                if old != new:
                    changes[fname] = (old, new)
        if changes:
            diff[key] = changes
    return diff


def _value_str(value: Any) -> str:
    from enum import Enum as _Enum

    if isinstance(value, _Enum):
        return f"{type(value).__name__}.{value.name}"
    return repr(value)


def _key_entity_cls(key: Any) -> type:
    return key.entity_cls if hasattr(key, "entity_cls") else key
