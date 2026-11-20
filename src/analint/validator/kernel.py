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
from collections.abc import Callable
from copyreg import dispatch_table
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum, EnumType
from itertools import chain
from types import GetSetDescriptorType
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Create, Delete, Set, Subtract
from analint.models.entity import Entity, EntityMeta, FieldDescriptor, FieldSpec, all_fields
from analint.models.expr import _AddExpr, _SubExpr
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
from analint.reporter.base import Code, Finding, Severity
from analint.validator.rule_checker import compile_operand, compile_predicate, evaluate, resolve
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
    # whether the action passed every pre/presence/terminal guard and began to
    # execute — true for ACCEPTED and for any defect raised after the guards
    # (effect/field/lifecycle/post), false for REJECTED and pre-evaluation errors
    entered: bool = False
    pre_context: dict | None = dc_field(default=None, repr=False)
    custom_copy: bool = dc_field(default=False, repr=False, compare=False)

    @property
    def changed_fields(self) -> dict:
        """Field-level diff of an accepted transition, computed on demand: only
        diagnostics read it, and diffing every explored edge was a hot spot."""
        if self.pre_context is None or self.post_context is None:
            return {}
        return _state_diff(self.pre_context, self.post_context)


def _trace_str(steps: list[str]) -> str:
    return " → ".join(steps) if steps else "(initial state)"


def _at(trace: list[str] | None) -> str:
    """Trace suffix naming the pre-state (a precondition is read there)."""
    return f" [at: {_trace_str(trace)}]" if trace is not None else ""


def _after(action: Action, trace: list[str] | None) -> str:
    """Trace suffix naming the state reached by firing the action."""
    return f" [after: {_trace_str([*trace, action.id])}]" if trace is not None else ""


@dataclass(frozen=True)
class _Plan:
    """The static part of an action's guards and effects, computed once."""

    guards: tuple  # (predicate, context keys it reads, compiled predicate)
    touched: frozenset  # Set/Add/Subtract target keys
    creates: tuple
    deletes: tuple
    frozen: frozenset  # targets the terminal lock protects (touched + deleted)
    writes: tuple[tuple[Any, str, Callable[[dict], Any]], ...]
    field_checks: tuple[tuple[Any, str, FieldSpec, bool], ...]  # bool marks Create
    lifecycle_checks: tuple[Lifecycle, ...]
    unchanged_lifecycle: tuple | None  # (target, field, reflexive value ids)
    presence_effects: tuple
    copy_types: dict  # target -> (declared type, eligible for a dict-only copy)
    changed: frozenset  # context slots any effect can write
    single_target: Any  # one possible changed slot, or None


_COPY_HOOKS = frozenset(
    {
        "__copy__",
        "__reduce__",
        "__reduce_ex__",
        "__getstate__",
        "__setstate__",
        "__getnewargs__",
        "__getnewargs_ex__",
        "__new__",
        "__getattribute__",
        "__getattr__",
        "__setattr__",
        "__class__",
        "__slots__",
    }
)


def _has_plain_copy(cls: type) -> bool:
    return (
        type(cls) is EntityMeta
        and issubclass(cls, Entity)
        and all(
            not _COPY_HOOKS.intersection(base.__dict__)
            and isinstance(base.__dict__.get("__dict__"), (GetSetDescriptorType, type(None)))
            for base in cls.__mro__
            if base is not object
        )
    )


def _compile_effect_value(effect: Set | Add | Subtract) -> Any:
    if isinstance(effect, Set):
        return compile_operand(effect.value)
    expr = _AddExpr if isinstance(effect, Add) else _SubExpr
    return compile_operand(expr(effect.field, effect.amount))


def _unchanged_lifecycle_reads(
    lifecycles: tuple[Lifecycle, ...], copy_types: dict, writes: list
) -> tuple | None:
    """Identify unwritten lifecycle fields whose comparison is usually a no-op."""
    written = {(key, name) for key, name, _ in writes}
    reads = []
    for lc in lifecycles:
        cls = lc._entity_cls
        descriptor = getattr(cls, lc.field_name, None)
        if type(descriptor) is not FieldDescriptor or descriptor.field_name != lc.field_name:
            return None
        for key, target_cls in copy_types.items():
            if target_cls is not cls:
                continue
            if (key, lc.field_name) in written:
                return None
            # Skip the old == new test only for known reflexive states. A
            # hand-built snapshot may carry NaN or a custom equality method.
            reflexive = frozenset(
                id(value)
                for value in (
                    lc.initial,
                    *lc.transitions,
                    *chain.from_iterable(lc.transitions.values()),
                )
                if type(type(value)) in (type, EnumType)
                and type(value).__eq__ in (object.__eq__, int.__eq__, str.__eq__)
            )
            reads.append((key, lc.field_name, reflexive))
    return tuple(reads)


def build_plan(action: Action, lifecycles: list[Lifecycle]) -> _Plan:
    """Compile the current declaration for one synchronous exploration.

    Actions remain editable between runs. A plan belongs to its caller, never
    to the Action, so later runs and copied actions cannot inherit stale guards.
    """
    writes = []
    field_checks = []
    creates = []
    deletes = []
    presence_effects = []
    for effect in action.effect:
        if isinstance(effect, (Set, Add, Subtract)):
            if is_field_ref(effect.field):
                key = field_context_key(effect.field)
                field_name = effect.field.field_name
                writes.append((key, field_name, _compile_effect_value(effect)))
                desc = all_fields(effect.field.entity_cls).get(field_name)
                if desc is not None and desc.spec is not None and desc.spec.has_constraints():
                    field_checks.append((key, field_name, desc.spec, False))
        elif isinstance(effect, Create):
            creates.append(
                (
                    effect.target,
                    tuple((name, compile_operand(v)) for name, v in effect.fields.items()),
                )
            )
            presence_effects.append(creates[-1])
            if isinstance(effect.target, InstanceRef):
                field_checks.extend(
                    (effect.target, name, desc.spec, True)
                    for name, desc in all_fields(effect.target.entity_cls).items()
                    if desc.spec is not None and desc.spec.has_constraints()
                )
        elif isinstance(effect, Delete):
            deletes.append(effect.target)
            presence_effects.append((effect.target, None))

    touched = frozenset(key for key, _, _ in writes)
    copy_types = {key: _key_entity_cls(key) for key in touched}
    touched_types = set(copy_types.values())
    changed = touched | {key for key, _ in presence_effects}
    lifecycle_checks = tuple(
        lc for lc in lifecycles if lc._entity_cls is None or lc._entity_cls in touched_types
    )
    return _Plan(
        guards=tuple(
            (
                pred,
                frozenset(field_context_key(r) for r in _collect_field_refs(pred)),
                compile_predicate(pred),
            )
            for pred in action.pre
        ),
        touched=touched,
        creates=tuple(creates),
        deletes=tuple(deletes),
        frozen=touched | set(deletes),
        writes=tuple(writes),
        field_checks=tuple(field_checks),
        lifecycle_checks=lifecycle_checks,
        unchanged_lifecycle=_unchanged_lifecycle_reads(lifecycle_checks, copy_types, writes),
        presence_effects=tuple(presence_effects),
        copy_types={key: (cls, _has_plain_copy(cls)) for key, cls in copy_types.items()},
        changed=changed,
        single_target=next(iter(changed)) if len(changed) == 1 else None,
    )


def step(
    spec: Spec,
    action: Action,
    context: dict,
    *,
    trace: list[str] | None = None,
    explain: bool = True,
    plan: _Plan | None = None,
) -> TransitionResult:
    """Evaluate one transition. See module docstring for outcome semantics.

    ``trace`` is the action-id path that reached ``context``; when given, defect
    findings are decorated with it so a counterexample reads end-to-end. Pass
    ``None`` (the default) for a single, context-free transition.

    ``explain=False`` skips building the reason of a REJECTED outcome (the
    explorer discards it); outcomes and defect findings are unchanged.
    """
    lifecycles = spec.lifecycles
    if plan is None:
        plan = build_plan(action, lifecycles)

    # ── pre guards: a false/absent precondition rejects; an error is a defect ──
    context_keys = context.keys()
    for pred, keys, holds in plan.guards:
        if not context_keys >= keys:
            # the predicate reads an entity intentionally absent from this state
            return (
                _rejected(action, Code.PRE_NOT_APPLICABLE, f"PRE not applicable: {_describe(pred)}")
                if explain
                else _silently_rejected()
            )
        try:
            if not holds(context):
                return (
                    _rejected(action, Code.PRE_FAILED, f"PRE failed: {_describe(pred)}")
                    if explain
                    else _silently_rejected()
                )
        except Exception as exc:
            return _defect(
                action,
                Code.EVALUATION_ERROR,
                f"pre evaluation error: {exc} (predicate: {_describe(pred)}){_at(trace)}",
            )

    # ── presence guards (Set/Add/Subtract target, Create, Delete) ─────────────
    for target in plan.touched:
        if isinstance(target, InstanceRef) and not is_present(context, target):
            return (
                _rejected(
                    action,
                    Code.PRESENCE_REJECTED,
                    f"cannot modify absent entity {target!r} with Set/Add/Subtract",
                )
                if explain
                else _silently_rejected()
            )
    for target, _ in plan.creates:
        if is_present(context, target):
            return (
                _rejected(
                    action,
                    Code.PRESENCE_REJECTED,
                    f"cannot create already-present entity {target!r}",
                )
                if explain
                else _silently_rejected()
            )
    for target in plan.deletes:
        if not is_present(context, target):
            return (
                _rejected(action, Code.PRESENCE_REJECTED, f"cannot delete absent entity {target!r}")
                if explain
                else _silently_rejected()
            )

    # ── terminal-state lock: an entity in a terminal lifecycle state is frozen,
    # against field changes and against deletion alike (a Create targets an
    # absent slot, which has no terminal state, so it is exempt) ──────────────
    for lc in lifecycles:
        if not lc.terminal:
            continue
        for target in plan.frozen:
            if _key_entity_cls(target) is not lc.entity_cls:
                continue
            inst = context.get(target)
            if inst is not None and getattr(inst, lc.field_name, None) in lc.terminal:
                if not explain:
                    return _silently_rejected()
                return TransitionResult(
                    Outcome.REJECTED,
                    findings=[
                        Finding(
                            Severity.ERROR,
                            f"lifecycle:{lc.id}",
                            f"{context_key_label(target)}.{lc.field_name}="
                            f"{getattr(inst, lc.field_name)!r} is terminal — "
                            f"the entity cannot be modified or deleted",
                            Code.TERMINAL_LOCKED,
                        )
                    ],
                )

    # Past the guards: the action executes, so every outcome from here counts as
    # having entered, whether it accepts or turns out to be a defect.

    # ── effects: simultaneous facts about the next state (effectless: unchanged) ─
    custom_copy = False
    if not action.effect:
        post = context
    else:
        try:
            post, custom_copy = _apply_effects(plan, context)
        except Exception as exc:
            return _entered(
                _defect(
                    action,
                    Code.EVALUATION_ERROR,
                    f"effect evaluation error: {exc}{_after(action, trace)}",
                )
            )
        # ── Field clamp / hard constraints, then lifecycle ────────────────────
        if plan.field_checks:
            field_defect = _check_field_constraints(action, plan.field_checks, post, trace)
            if field_defect is not None:
                return _entered(field_defect)
        checks = lifecycles if custom_copy else plan.lifecycle_checks
        if checks and (
            custom_copy
            or plan.unchanged_lifecycle is None
            or any(
                key in context and id(context[key].__dict__.get(name)) not in known
                for key, name, known in plan.unchanged_lifecycle
            )
        ):
            lifecycle_defect = _check_lifecycle_transitions(
                action, context, post, checks, trace, None if custom_copy else plan.single_target
            )
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
        pre_context=context,
        entered=True,
        custom_copy=custom_copy,
    )


def _silently_rejected() -> TransitionResult:
    return TransitionResult(Outcome.REJECTED)


def _rejected(action: Action, code: Code, message: str) -> TransitionResult:
    return TransitionResult(
        Outcome.REJECTED,
        findings=[Finding(Severity.ERROR, f"action:{action.id}", message, code)],
    )


def _defect(action: Action, code: Code, message: str) -> TransitionResult:
    return TransitionResult(
        Outcome.DEFECT,
        findings=[Finding(Severity.ERROR, f"action:{action.id}", message, code)],
    )


def _entered(result: TransitionResult) -> TransitionResult:
    result.entered = True
    return result


def _apply_effects(plan: _Plan, context: dict) -> tuple[dict, bool]:
    """Copy effect targets and evaluate every RHS against the pre-state."""
    updates = [(key, name, value(context)) for key, name, value in plan.writes if key in context]

    # Preserve copy-on-write and copy order. Clamps later mutate only copies.
    post = dict(context)
    custom_copy = False
    for key in {key for key, _, _ in updates}:
        before = post[key]
        cls, plain = plan.copy_types[key]
        if plain and type(before) is cls and cls not in dispatch_table:
            after = object.__new__(cls)
            after.__dict__.update(before.__dict__)
        else:
            after = copy.copy(before)
            custom_copy = True
        post[key] = after
    for key, field_name, value in updates:
        entity = post.get(key)
        if entity is not None:
            entity.__dict__[field_name] = value
    for target, fields in plan.presence_effects:
        if fields is None:
            post[target] = Absent(target)
        else:
            resolved = {name: value(context) for name, value in fields}
            post[target] = present_snapshot(target, resolved)
    return post, custom_copy


def _check_field_constraints(
    action: Action,
    checks: tuple[tuple[Any, str, FieldSpec, bool], ...],
    post: dict,
    trace: list[str] | None,
) -> TransitionResult | None:
    """Clamp saturating fields and report the first hard constraint violation."""
    for key, name, spec, created in checks:
        inst = post.get(key)
        if inst is None:
            continue
        value = inst.__dict__.get(name)
        problem = spec.violation(value)
        if problem is None:
            continue
        if spec.saturate:
            value = spec.clamp(value)
            inst.__dict__[name] = value
            problem = spec.violation(value)
            if problem is None:
                continue
        label = f"created {key!r}" if created else context_key_label(key)
        return _defect(
            action,
            Code.FIELD_CONSTRAINT,
            f"field constraint violated: {label}.{name} {problem}{_after(action, trace)}",
        )
    return None


def _check_lifecycle_transitions(
    action: Action,
    ctx: dict,
    post: dict,
    lifecycles: list[Lifecycle] | tuple[Lifecycle, ...],
    trace: list[str] | None,
    single_target: Any,
) -> TransitionResult | None:
    """A change to a lifecycle field must follow a declared transition."""
    # untouched entities are shared by copy-on-write; scan only the changed
    # ones, in context order, so the first defect reported is unchanged
    if single_target is None:
        changed = [(key, inst) for key, inst in ctx.items() if post.get(key) is not inst]
    else:
        inst = ctx.get(single_target)
        changed = [(single_target, inst)] if inst is not post.get(single_target) else []
    if not changed:
        return None
    for lc in lifecycles:
        entity_cls = lc.entity_cls
        for context_key, inst_pre in changed:
            if type(inst_pre) is not entity_cls:
                continue
            inst_post = post.get(context_key)
            if inst_post is None:
                continue  # absent
            # a created/deleted slot's lifecycle field is an initial assignment
            # or a teardown, not a declared transition
            if not is_present(ctx, context_key) or not is_present(post, context_key):
                continue
            old = getattr(inst_pre, lc.field_name, None)
            new = getattr(inst_post, lc.field_name, None)
            if old == new:
                continue
            allowed = set(lc.transitions.get(old, ()))
            if new not in allowed:
                return _defect(
                    action,
                    Code.UNDECLARED_LIFECYCLE_EDGE,
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
                Code.EVALUATION_ERROR,
                f"post evaluation error: {exc} (predicate: {_describe(pred)})"
                f"{_after(action, trace)}",
            )
        if not ok:
            return _defect(
                action,
                Code.POSTCONDITION_VIOLATED,
                f"violates its postcondition {_describe(pred)}{_after(action, trace)}",
            )
    return None


def _materialize_emitted(
    action: Action, post: dict, trace: list[str] | None
) -> tuple[list, TransitionResult | None]:
    """Resolve each emitted event's payload templates against the next state.

    A bare ``Event`` class carries no payload and passes through unchanged. An
    ``Event`` instance whose field templates cannot be resolved (a type error, a
    reference to an absent entity) is a model defect, not a silent emission.
    Payload constraints validate the resolved values without clamping: event
    construction, unlike state effects, does not apply ``saturate``."""
    materialized: list = []
    for event in action.emits:
        if isinstance(event, type):
            materialized.append(event)
            continue
        cls = type(event)
        try:
            fields = all_fields(cls)
            values = {fname: resolve(event.__dict__.get(fname), post) for fname in fields}
            for fname, desc in fields.items():
                if desc.spec is None:
                    continue
                problem = desc.spec.violation(values[fname])
                if problem is not None:
                    return [], _defect(
                        action,
                        Code.FIELD_CONSTRAINT,
                        f"field constraint violated: emitted {cls.__name__}.{fname} "
                        f"{problem}{_after(action, trace)}",
                    )
            materialized.append(cls(**values))
        except Exception as exc:
            return [], _defect(
                action,
                Code.EVALUATION_ERROR,
                f"emitted payload evaluation error: {exc} "
                f"(event: {cls.__name__}){_after(action, trace)}",
            )
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
