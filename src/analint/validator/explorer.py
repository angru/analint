"""Bounded reachability: exhaustive BFS over the spec's state space.

State = the field values of one instance per entity type (singletons).
Transitions = actions whose preconditions hold. The space is finite when
fields are enums/bools and numeric fields either converge or carry declared
Field constraints; otherwise exploration stops at max_states and queries report
INCONCLUSIVE instead of pretending.

Every answer comes with a trace — the sequence of action ids from the
initial state — because a counterexample you can read beats a verdict.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Set, Subtract
from analint.models.entity import FieldDescriptor, all_fields
from analint.models.lifecycle import Lifecycle
from analint.models.predicate import Predicate
from analint.models.query import (
    AlwaysHolds,
    DeadActions,
    NoDeadEnd,
    Reachable,
    Unreachable,
)
from analint.models.root import Spec
from analint.reporter.base import Finding, QueryResult, Severity
from analint.validator.rule_checker import evaluate
from analint.validator.scenario_runner import _apply_effects
from analint.validator.structural import _collect_field_refs, _describe

StateKey = tuple[Any, ...]
Query = Reachable | Unreachable | AlwaysHolds | NoDeadEnd | DeadActions

# ── Exploration result ─────────────────────────────────────────────────────────


@dataclass
class Exploration:
    states: dict = dc_field(default_factory=dict)  # key → context
    order: list = dc_field(default_factory=list)  # keys in BFS order
    edges: list = dc_field(default_factory=list)  # (key, action_id, key)
    parents: dict = dc_field(default_factory=dict)  # key → (prev_key, action_id)
    fired: set = dc_field(default_factory=set)  # action ids ever enabled
    findings: list = dc_field(default_factory=list)  # violations met en route
    excluded: dict = dc_field(default_factory=dict)  # action id → why it is not explorable
    capped: bool = False
    _seen: set = dc_field(default_factory=set)

    def report_once(self, severity: Severity, loc: str, message: str) -> None:
        """Deduplicated finding — a model error would otherwise repeat per state."""
        if (loc, message) in self._seen:
            return
        self._seen.add((loc, message))
        self.findings.append(Finding(severity, loc, message))

    def trace_to(self, key: StateKey) -> list[str]:
        steps: list[str] = []
        while True:
            prev, action_id = self.parents[key]
            if prev is None:
                return list(reversed(steps))
            steps.append(action_id)
            key = prev


# ── State helpers ──────────────────────────────────────────────────────────────


def state_key(ctx: dict) -> tuple:
    items = []
    for cls in sorted(ctx, key=lambda c: c.__name__):
        inst = ctx[cls]
        for f in sorted(all_fields(cls)):
            items.append((cls.__name__, f, inst.__dict__.get(f)))
    return tuple(items)


def render_state(ctx: dict) -> dict:
    out = {}
    for cls in sorted(ctx, key=lambda c: c.__name__):
        inst = ctx[cls]
        for f in sorted(all_fields(cls)):
            out[f"{cls.__name__}.{f}"] = _value_str(inst.__dict__.get(f))
    return out


def _value_str(value: Any) -> str:
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    return repr(value)


def _trace_str(steps: list[str]) -> str:
    return " → ".join(steps) if steps else "(initial state)"


# ── Initial state ──────────────────────────────────────────────────────────────


def build_initial(spec: Spec, given: list) -> tuple[dict | None, str | None]:
    """Initial context: `given` instances + defaults-built entities.

    Entities without full defaults are allowed only when no action or
    invariant references them; otherwise the query must supply them.
    """
    ctx: dict = {}
    for inst in given:
        ctx[type(inst)] = copy.copy(inst)

    missing: list[type] = []
    for cls in spec.entities:
        if cls in ctx:
            continue
        try:
            ctx[cls] = cls()
        except TypeError:
            missing.append(cls)

    if missing:
        needed: set[type] = set()
        for action in spec.actions:
            for pred in list(action.pre) + list(action.post):
                needed.update(r.entity_cls for r in _collect_field_refs(pred))
            for e in action.effect:
                if isinstance(e, (Set, Subtract, Add)) and isinstance(e.field, FieldDescriptor):
                    needed.add(e.field.entity_cls)
        for inv in spec.invariants:
            needed.update(r.entity_cls for r in _collect_field_refs(inv.expression))
        blocked = [c.__name__ for c in missing if c in needed]
        if blocked:
            return None, (
                f"entities without full defaults need initial instances: "
                f"{', '.join(sorted(blocked))} — pass given=[...] in the query"
            )

    # the explored state must be hashable — reject unsupported field domains
    # up front instead of crashing inside state_key
    for cls, inst in ctx.items():
        for fname in all_fields(cls):
            value = inst.__dict__.get(fname)
            try:
                hash(value)
            except TypeError:
                return None, (
                    f"{cls.__name__}.{fname} holds an unhashable value {value!r} — "
                    f"the engine supports scalar, enum, str and bool fields only"
                )
    return ctx, None


# ── Exploration ────────────────────────────────────────────────────────────────


def explore(spec: Spec, initial_ctx: dict, max_states: int) -> Exploration:
    # Field constraints double as the engine's bounds (research/13)
    bounds_map = {
        (cls, fname): desc.spec
        for cls in spec.entities
        for fname, desc in all_fields(cls).items()
        if desc.spec is not None and desc.spec.has_constraints()
    }
    lifecycles = list(spec.lifecycles)

    exp = Exploration()

    # Actions whose preconditions reference event payloads are not explorable:
    # events are not part of the state. Report explicitly instead of silently
    # never enabling them (research/14 §7.5).
    state_types = set(spec.entities)
    for action in spec.actions:
        foreign = {
            r.entity_cls.__name__
            for pred in action.pre
            for r in _collect_field_refs(pred)
            if r.entity_cls not in state_types
        }
        if foreign:
            exp.excluded[action.id] = (
                f"preconditions reference {', '.join(sorted(foreign))}, which is "
                f"not part of the explored state (event payloads are outside "
                f"the engine's state model)"
            )
            exp.report_once(
                Severity.WARNING,
                f"action:{action.id}",
                f"excluded from exploration: {exp.excluded[action.id]}",
            )

    key0 = state_key(initial_ctx)
    exp.states[key0] = initial_ctx
    exp.order.append(key0)
    exp.parents[key0] = (None, None)
    _report_invariant_violations(spec, initial_ctx, key0, exp)

    queue = [key0]
    while queue:
        if len(exp.states) >= max_states:
            exp.capped = True
            break
        key = queue.pop(0)
        ctx = exp.states[key]

        for action in spec.actions:
            if action.id in exp.excluded:
                continue
            if not _enabled(action, ctx, lifecycles, exp, key):
                continue
            exp.fired.add(action.id)
            if not action.effect:
                exp.edges.append((key, action.id, key))
                continue
            try:
                post = _apply_effects(action.effect, ctx)
            except Exception as exc:
                exp.report_once(
                    Severity.ERROR,
                    f"action:{action.id}",
                    f"effect evaluation error during exploration: {exc} "
                    f"[after: {_trace_str(exp.trace_to(key))}]",
                )
                continue

            if not _check_bounds(action, ctx, post, bounds_map, key, exp):
                continue
            if not _check_lifecycle_transitions(action, ctx, post, lifecycles, key, exp):
                continue

            try:
                k2 = state_key(post)
            except TypeError as exc:
                exp.report_once(
                    Severity.ERROR,
                    f"action:{action.id}",
                    f"'{action.id}' produces an unhashable state value ({exc}) — "
                    f"the engine supports scalar, enum, str and bool fields only",
                )
                continue
            exp.edges.append((key, action.id, k2))
            if k2 in exp.states:
                continue
            exp.states[k2] = post
            exp.order.append(k2)
            exp.parents[k2] = (key, action.id)
            if _report_invariant_violations(spec, post, k2, exp):
                continue  # illegal state: reported, not expanded further
            queue.append(k2)

    return exp


def _enabled(
    action: Action, ctx: dict, lifecycles: list[Lifecycle], exp: Exploration, key: StateKey
) -> bool:
    for pred in action.pre:
        refs = _collect_field_refs(pred)
        if any(r.entity_cls not in ctx for r in refs):
            return False  # entity intentionally absent from this state
        try:
            if not evaluate(pred, ctx):
                return False
        except Exception as exc:
            # a model/type error is never "the action is just disabled"
            exp.report_once(
                Severity.ERROR,
                f"action:{action.id}",
                f"pre evaluation error: {exc} (predicate: {_describe(pred)}) "
                f"[at: {_trace_str(exp.trace_to(key))}]",
            )
            return False

    touched = {
        e.field.entity_cls
        for e in action.effect
        if isinstance(e, (Set, Subtract, Add)) and isinstance(e.field, FieldDescriptor)
    }
    for lc in lifecycles:
        if not lc.terminal or lc.entity_cls not in touched:
            continue
        inst = ctx.get(lc.entity_cls)
        if inst is not None and getattr(inst, lc.field_name, None) in lc.terminal:
            return False
    return True


def _check_bounds(
    action: Action,
    ctx: dict,
    post: dict,
    bounds_map: dict,
    key: StateKey,
    exp: Exploration,
) -> bool:
    """Clamp saturating fields; report and prune on hard constraint violations."""
    for effect in action.effect:
        if not isinstance(effect, (Set, Subtract, Add)):
            continue
        target = (effect.field.entity_cls, effect.field.field_name)
        spec = bounds_map.get(target)
        if spec is None or target[0] not in post:
            continue
        inst = post[target[0]]
        value = inst.__dict__.get(target[1])
        problem = spec.violation(value)
        if problem is None:
            continue
        if spec.saturate:
            inst.__dict__[target[1]] = spec.clamp(value)
            continue
        exp.findings.append(
            Finding(
                Severity.ERROR,
                f"action:{action.id}",
                f"'{action.id}' drives {target[0].__name__}.{target[1]} out of its "
                f"declared range: {problem} "
                f"[after: {_trace_str([*exp.trace_to(key), action.id])}]",
            )
        )
        return False
    return True


def _check_lifecycle_transitions(
    action: Action,
    ctx: dict,
    post: dict,
    lifecycles: list[Lifecycle],
    key: StateKey,
    exp: Exploration,
) -> bool:
    """A Set on a lifecycle field must follow a declared transition."""
    for lc in lifecycles:
        inst_pre = ctx.get(lc.entity_cls)
        inst_post = post.get(lc.entity_cls)
        if inst_pre is None or inst_post is None:
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
            exp.findings.append(
                Finding(
                    Severity.ERROR,
                    f"action:{action.id}",
                    f"'{action.id}' performs {lc.entity_cls.__name__}.{lc.field_name} "
                    f"{_value_str(old)} → {_value_str(new)}, not declared in "
                    f"lifecycle '{lc.id}' "
                    f"[after: {_trace_str([*exp.trace_to(key), action.id])}]",
                )
            )
            return False
    return True


def _report_invariant_violations(spec: Spec, ctx: dict, key: StateKey, exp: Exploration) -> bool:
    violated = False
    for inv in spec.invariants:
        refs = _collect_field_refs(inv.expression)
        if any(r.entity_cls not in ctx for r in refs):
            continue
        try:
            ok = evaluate(inv.expression, ctx)
        except Exception as exc:
            exp.report_once(
                Severity.ERROR,
                f"invariant:{inv.id}",
                f"evaluation error: {exc} [at: {_trace_str(exp.trace_to(key))}]",
            )
            continue
        if not ok:
            violated = True
            exp.findings.append(
                Finding(
                    Severity.ERROR,
                    f"invariant:{inv.id}",
                    f"invariant '{inv.label or _describe(inv.expression)}' breaks "
                    f"[after: {_trace_str(exp.trace_to(key))}]",
                )
            )
    return violated


# ── Query evaluation ───────────────────────────────────────────────────────────


def run_query(query: Query, spec: Spec, cache: dict) -> QueryResult:
    qid = query.id or type(query).__name__
    kind = type(query).__name__

    initial, error = build_initial(spec, query.given)
    if initial is None:
        return QueryResult(
            query_id=qid,
            kind=kind,
            status="FAIL",
            findings=[
                Finding(
                    Severity.ERROR,
                    f"query:{qid}",
                    error or "could not build the initial state",
                )
            ],
        )

    cache_key = (state_key(initial), query.max_states)
    if cache_key not in cache:
        cache[cache_key] = explore(spec, initial, query.max_states)
    exp = cache[cache_key]

    if isinstance(query, Reachable):
        return _eval_reachable(query, qid, exp, expect_reachable=True)
    if isinstance(query, Unreachable):
        return _eval_reachable(query, qid, exp, expect_reachable=False)
    if isinstance(query, AlwaysHolds):
        return _eval_always(query, qid, exp)
    if isinstance(query, NoDeadEnd):
        return _eval_no_dead_end(query, qid, exp)
    if isinstance(query, DeadActions):
        return _eval_dead_actions(query, qid, exp, spec)
    return QueryResult(
        query_id=qid,
        kind=kind,
        status="FAIL",
        findings=[Finding(Severity.ERROR, f"query:{qid}", f"unknown query type {kind}")],
    )


@dataclass
class _Scan:
    """Strict predicate scan over explored states (research/14 §7.2).

    Distinguishes: matched / applicable-but-false / never applicable /
    evaluation errors — so a model error can never read as a verdict.
    """

    first_match: StateKey | None = None
    applicable: int = 0
    errors: list = dc_field(default_factory=list)


def _scan_states(exp: Exploration, predicate: Predicate) -> _Scan:
    scan = _Scan()
    refs = _collect_field_refs(predicate)
    for key in exp.order:
        ctx = exp.states[key]
        if any(r.entity_cls not in ctx for r in refs):
            continue
        scan.applicable += 1
        try:
            if evaluate(predicate, ctx) and scan.first_match is None:
                scan.first_match = key
        except Exception as exc:
            message = f"evaluation error: {exc} [at: {_trace_str(exp.trace_to(key))}]"
            if message not in scan.errors:
                scan.errors.append(message)
    return scan


def _model_error_result(qid: str, kind: str, exp: Exploration, problems: list[str]) -> QueryResult:
    return QueryResult(
        query_id=qid,
        kind=kind,
        status="FAIL",
        states_explored=len(exp.states),
        findings=[Finding(Severity.ERROR, f"query:{qid}", p) for p in problems],
    )


def _never_applicable_result(qid: str, kind: str, exp: Exploration, text: str) -> QueryResult:
    return QueryResult(
        query_id=qid,
        kind=kind,
        status="FAIL",
        states_explored=len(exp.states),
        findings=[
            Finding(
                Severity.ERROR,
                f"query:{qid}",
                f"'{text}' was not applicable in any explored state — it references "
                f"types that are never part of the state (event payloads or missing "
                f"entities); the verdict would be vacuous",
            )
        ],
    )


def _eval_reachable(
    query: Reachable | Unreachable,
    qid: str,
    exp: Exploration,
    expect_reachable: bool,
) -> QueryResult:
    kind = type(query).__name__
    text = query.label or _describe(query.predicate)
    scan = _scan_states(exp, query.predicate)
    if scan.errors:
        return _model_error_result(qid, kind, exp, scan.errors)
    if scan.applicable == 0:
        return _never_applicable_result(qid, kind, exp, text)
    found = scan.first_match

    if found is not None:
        trace = exp.trace_to(found)
        if expect_reachable:
            return QueryResult(
                query_id=qid,
                kind=kind,
                status="PASS",
                states_explored=len(exp.states),
                trace=trace,
                findings=[
                    Finding(
                        Severity.INFO, f"query:{qid}", f"'{text}' reachable: {_trace_str(trace)}"
                    )
                ],
            )
        return QueryResult(
            query_id=qid,
            kind=kind,
            status="FAIL",
            states_explored=len(exp.states),
            trace=trace,
            findings=[
                Finding(
                    Severity.ERROR,
                    f"query:{qid}",
                    f"'{text}' must be unreachable, but: {_trace_str(trace)}",
                )
            ],
        )

    if exp.capped:
        return _inconclusive(qid, kind, exp)
    if expect_reachable:
        return QueryResult(
            query_id=qid,
            kind=kind,
            status="FAIL",
            states_explored=len(exp.states),
            findings=[
                Finding(
                    Severity.ERROR,
                    f"query:{qid}",
                    f"'{text}' is not reachable (explored all {len(exp.states)} states)",
                )
            ],
        )
    return QueryResult(query_id=qid, kind=kind, status="PASS", states_explored=len(exp.states))


def _eval_always(query: AlwaysHolds, qid: str, exp: Exploration) -> QueryResult:
    text = query.label or _describe(query.predicate)
    refs = _collect_field_refs(query.predicate)
    applicable = 0
    errors: list[str] = []
    for key in exp.order:
        ctx = exp.states[key]
        if any(r.entity_cls not in ctx for r in refs):
            continue
        applicable += 1
        try:
            ok = evaluate(query.predicate, ctx)
        except Exception as exc:
            message = f"evaluation error: {exc} [at: {_trace_str(exp.trace_to(key))}]"
            if message not in errors:
                errors.append(message)
            continue
        if not ok:
            trace = exp.trace_to(key)
            return QueryResult(
                query_id=qid,
                kind="AlwaysHolds",
                status="FAIL",
                states_explored=len(exp.states),
                trace=trace,
                findings=[
                    Finding(
                        Severity.ERROR,
                        f"query:{qid}",
                        f"'{text}' breaks: {_trace_str(trace)} ⇒ "
                        f"{_offending_values(query.predicate, ctx)}",
                    )
                ],
            )
    if errors:
        return _model_error_result(qid, "AlwaysHolds", exp, errors)
    if applicable == 0:
        return _never_applicable_result(qid, "AlwaysHolds", exp, text)
    if exp.capped:
        return _inconclusive(qid, "AlwaysHolds", exp)
    return QueryResult(
        query_id=qid, kind="AlwaysHolds", status="PASS", states_explored=len(exp.states)
    )


def _eval_no_dead_end(query: NoDeadEnd, qid: str, exp: Exploration) -> QueryResult:
    text = query.label or _describe(query.goal)
    if exp.capped:
        return _inconclusive(qid, "NoDeadEnd", exp)

    refs = _collect_field_refs(query.goal)
    applicable = 0
    errors: list[str] = []
    goal_states = set()
    for key in exp.order:
        ctx = exp.states[key]
        if any(r.entity_cls not in ctx for r in refs):
            continue
        applicable += 1
        try:
            if evaluate(query.goal, ctx):
                goal_states.add(key)
        except Exception as exc:
            message = f"evaluation error: {exc} [at: {_trace_str(exp.trace_to(key))}]"
            if message not in errors:
                errors.append(message)

    if errors:
        return _model_error_result(qid, "NoDeadEnd", exp, errors)
    if applicable == 0:
        return _never_applicable_result(qid, "NoDeadEnd", exp, text)
    if not goal_states:
        return QueryResult(
            query_id=qid,
            kind="NoDeadEnd",
            status="FAIL",
            states_explored=len(exp.states),
            findings=[
                Finding(Severity.ERROR, f"query:{qid}", f"goal '{text}' is not reachable at all")
            ],
        )

    reverse: dict = {}
    for src, _, dst in exp.edges:
        reverse.setdefault(dst, set()).add(src)
    co_reachable = set(goal_states)
    stack = list(goal_states)
    while stack:
        node = stack.pop()
        for prev in reverse.get(node, ()):
            if prev not in co_reachable:
                co_reachable.add(prev)
                stack.append(prev)

    for key in exp.order:  # BFS order → shortest trace to the first dead end
        if key not in co_reachable:
            trace = exp.trace_to(key)
            return QueryResult(
                query_id=qid,
                kind="NoDeadEnd",
                status="FAIL",
                states_explored=len(exp.states),
                trace=trace,
                findings=[
                    Finding(
                        Severity.ERROR,
                        f"query:{qid}",
                        f"dead end: after {_trace_str(trace)} the goal "
                        f"'{text}' can no longer be reached",
                    )
                ],
            )
    return QueryResult(
        query_id=qid, kind="NoDeadEnd", status="PASS", states_explored=len(exp.states)
    )


def _eval_dead_actions(query: DeadActions, qid: str, exp: Exploration, spec: Spec) -> QueryResult:
    # Actions excluded from exploration (event-payload preconditions) are not
    # "dead" — they are outside the engine's state model and reported as such.
    dead = sorted(a.id for a in spec.actions if a.id not in exp.fired and a.id not in exp.excluded)
    notes = [
        Finding(
            Severity.INFO,
            f"query:{qid}",
            f"not assessed (excluded from exploration): {aid} — {reason}",
        )
        for aid, reason in sorted(exp.excluded.items())
    ]
    if not dead:
        return QueryResult(
            query_id=qid,
            kind="DeadActions",
            status="PASS",
            states_explored=len(exp.states),
            findings=notes,
        )
    if exp.capped:
        return _inconclusive(qid, "DeadActions", exp)
    return QueryResult(
        query_id=qid,
        kind="DeadActions",
        status="FAIL",
        states_explored=len(exp.states),
        findings=[
            Finding(
                Severity.ERROR,
                f"query:{qid}",
                f"never enabled in any reachable state: {', '.join(dead)}",
            ),
            *notes,
        ],
    )


def _inconclusive(qid: str, kind: str, exp: Exploration) -> QueryResult:
    return QueryResult(
        query_id=qid,
        kind=kind,
        status="INCONCLUSIVE",
        states_explored=len(exp.states),
        findings=[
            Finding(
                Severity.WARNING,
                f"query:{qid}",
                f"state space exceeded max_states={len(exp.states)} — "
                f"add Field constraints to numeric fields or raise max_states",
            )
        ],
    )


def _offending_values(predicate: Predicate, ctx: dict) -> str:
    parts = []
    for ref in _collect_field_refs(predicate):
        inst = ctx.get(ref.entity_cls)
        if inst is not None:
            parts.append(
                f"{ref.entity_cls.__name__}.{ref.field_name}="
                f"{_value_str(getattr(inst, ref.field_name, None))}"
            )
    return ", ".join(parts)
