"""Bounded reachability: exhaustive BFS over the spec's state space.

State = the field values of one instance per entity type (singletons).
Transitions = actions whose preconditions hold. The space is finite when
fields are enums/bools and numeric fields either converge or carry declared
Bounds; otherwise exploration stops at max_states and queries report
INCONCLUSIVE instead of pretending.

Every answer comes with a trace — the sequence of action ids from the
initial state — because a counterexample you can read beats a verdict.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field as dc_field
from enum import Enum

from analint.models.effect import Add, Set, Subtract
from analint.models.entity import FieldDescriptor
from analint.models.query import (
    AlwaysHolds, Bounds, DeadActions, NoDeadEnd, Reachable, Unreachable,
)
from analint.models.root import Spec
from analint.reporter.base import Finding, QueryResult, Severity
from analint.validator.rule_checker import evaluate
from analint.validator.scenario_runner import _apply_effects
from analint.validator.structural import _collect_field_refs, _describe


# ── Exploration result ─────────────────────────────────────────────────────────

@dataclass
class Exploration:
    states: dict = dc_field(default_factory=dict)    # key → context
    order: list = dc_field(default_factory=list)     # keys in BFS order
    edges: list = dc_field(default_factory=list)     # (key, action_id, key)
    parents: dict = dc_field(default_factory=dict)   # key → (prev_key, action_id)
    fired: set = dc_field(default_factory=set)       # action ids ever enabled
    findings: list = dc_field(default_factory=list)  # violations met en route
    capped: bool = False

    def trace_to(self, key) -> list[str]:
        steps: list[str] = []
        while True:
            prev, action_id = self.parents[key]
            if prev is None:
                return list(reversed(steps))
            steps.append(action_id)
            key = prev


# ── State helpers ──────────────────────────────────────────────────────────────

def _all_fields(cls) -> list[str]:
    fields: dict = {}
    for klass in reversed(cls.__mro__):
        fields.update(getattr(klass, "_own_fields", {}))
    return sorted(fields)


def state_key(ctx: dict) -> tuple:
    items = []
    for cls in sorted(ctx, key=lambda c: c.__name__):
        inst = ctx[cls]
        for f in _all_fields(cls):
            items.append((cls.__name__, f, inst.__dict__.get(f)))
    return tuple(items)


def render_state(ctx: dict) -> dict:
    out = {}
    for cls in sorted(ctx, key=lambda c: c.__name__):
        inst = ctx[cls]
        for f in _all_fields(cls):
            out[f"{cls.__name__}.{f}"] = _value_str(inst.__dict__.get(f))
    return out


def _value_str(value) -> str:
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
            return None, (f"entities without full defaults need initial instances: "
                          f"{', '.join(sorted(blocked))} — pass given=[...] in the query")
    return ctx, None


# ── Exploration ────────────────────────────────────────────────────────────────

def explore(spec: Spec, initial_ctx: dict, max_states: int) -> Exploration:
    bounds_map = {
        (b.field.entity_cls, b.field.field_name): b
        for b in spec.bounds
        if isinstance(b.field, FieldDescriptor)
    }
    lifecycles = [lc for lc in spec.lifecycles if isinstance(lc.field, FieldDescriptor)]

    exp = Exploration()
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
            if not _enabled(action, ctx, lifecycles):
                continue
            exp.fired.add(action.id)
            if not action.effect:
                exp.edges.append((key, action.id, key))
                continue
            try:
                post = _apply_effects(action.effect, ctx)
            except Exception as exc:
                exp.findings.append(Finding(
                    Severity.ERROR, f"action:{action.id}",
                    f"effect evaluation error during exploration: {exc} "
                    f"[after: {_trace_str(exp.trace_to(key))}]"))
                continue

            if not _check_bounds(action, ctx, post, bounds_map, key, exp):
                continue
            if not _check_lifecycle_transitions(action, ctx, post, lifecycles, key, exp):
                continue

            k2 = state_key(post)
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


def _enabled(action, ctx: dict, lifecycles: list) -> bool:
    for pred in action.pre:
        refs = _collect_field_refs(pred)
        if any(r.entity_cls not in ctx for r in refs):
            return False  # references something outside the state (e.g. event payload)
        try:
            if not evaluate(pred, ctx):
                return False
        except Exception:
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


def _check_bounds(action, ctx: dict, post: dict, bounds_map: dict, key, exp: Exploration) -> bool:
    """Clamp saturating fields; report and prune on hard bound violations."""
    for effect in action.effect:
        if not isinstance(effect, (Set, Subtract, Add)):
            continue
        target = (effect.field.entity_cls, effect.field.field_name)
        b = bounds_map.get(target)
        if b is None or target[0] not in post:
            continue
        inst = post[target[0]]
        value = inst.__dict__.get(target[1])
        if value is None or b.min <= value <= b.max:
            continue
        if b.saturate:
            inst.__dict__[target[1]] = b.min if value < b.min else b.max
            continue
        exp.findings.append(Finding(
            Severity.ERROR, f"action:{action.id}",
            f"'{action.id}' drives {target[0].__name__}.{target[1]} to "
            f"{_value_str(value)}, outside bounds [{b.min}, {b.max}] "
            f"[after: {_trace_str(exp.trace_to(key) + [action.id])}]"))
        return False
    return True


def _check_lifecycle_transitions(action, ctx: dict, post: dict, lifecycles: list,
                                 key, exp: Exploration) -> bool:
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
            exp.findings.append(Finding(
                Severity.ERROR, f"action:{action.id}",
                f"'{action.id}' performs {lc.entity_cls.__name__}.{lc.field_name} "
                f"{_value_str(old)} → {_value_str(new)}, not declared in "
                f"lifecycle '{lc.id}' "
                f"[after: {_trace_str(exp.trace_to(key) + [action.id])}]"))
            return False
    return True


def _report_invariant_violations(spec: Spec, ctx: dict, key, exp: Exploration) -> bool:
    violated = False
    for inv in spec.invariants:
        refs = _collect_field_refs(inv.expression)
        if any(r.entity_cls not in ctx for r in refs):
            continue
        try:
            ok = evaluate(inv.expression, ctx)
        except Exception:
            continue
        if not ok:
            violated = True
            exp.findings.append(Finding(
                Severity.ERROR, f"invariant:{inv.id}",
                f"invariant '{inv.label or _describe(inv.expression)}' breaks "
                f"[after: {_trace_str(exp.trace_to(key))}]"))
    return violated


# ── Query evaluation ───────────────────────────────────────────────────────────

def run_query(query, spec: Spec, cache: dict) -> QueryResult:
    qid = query.id or type(query).__name__
    kind = type(query).__name__

    initial, error = build_initial(spec, query.given)
    if initial is None:
        return QueryResult(query_id=qid, kind=kind, status="FAIL",
                           findings=[Finding(Severity.ERROR, f"query:{qid}", error)])

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
    return QueryResult(query_id=qid, kind=kind, status="FAIL",
                       findings=[Finding(Severity.ERROR, f"query:{qid}",
                                         f"unknown query type {kind}")])


def _find_state(exp: Exploration, predicate) -> tuple | None:
    for key in exp.order:
        ctx = exp.states[key]
        refs = _collect_field_refs(predicate)
        if any(r.entity_cls not in ctx for r in refs):
            continue
        try:
            if evaluate(predicate, ctx):
                return key
        except Exception:
            continue
    return None


def _eval_reachable(query, qid: str, exp: Exploration, expect_reachable: bool) -> QueryResult:
    kind = type(query).__name__
    text = query.label or _describe(query.predicate)
    found = _find_state(exp, query.predicate)

    if found is not None:
        trace = exp.trace_to(found)
        if expect_reachable:
            return QueryResult(
                query_id=qid, kind=kind, status="PASS",
                states_explored=len(exp.states), trace=trace,
                findings=[Finding(Severity.INFO, f"query:{qid}",
                                  f"'{text}' reachable: {_trace_str(trace)}")])
        return QueryResult(
            query_id=qid, kind=kind, status="FAIL",
            states_explored=len(exp.states), trace=trace,
            findings=[Finding(Severity.ERROR, f"query:{qid}",
                              f"'{text}' must be unreachable, but: {_trace_str(trace)}")])

    if exp.capped:
        return _inconclusive(qid, kind, exp)
    if expect_reachable:
        return QueryResult(
            query_id=qid, kind=kind, status="FAIL", states_explored=len(exp.states),
            findings=[Finding(Severity.ERROR, f"query:{qid}",
                              f"'{text}' is not reachable "
                              f"(explored all {len(exp.states)} states)")])
    return QueryResult(query_id=qid, kind=kind, status="PASS",
                       states_explored=len(exp.states))


def _eval_always(query, qid: str, exp: Exploration) -> QueryResult:
    text = query.label or _describe(query.predicate)
    for key in exp.order:
        ctx = exp.states[key]
        refs = _collect_field_refs(query.predicate)
        if any(r.entity_cls not in ctx for r in refs):
            continue
        try:
            ok = evaluate(query.predicate, ctx)
        except Exception:
            continue
        if not ok:
            trace = exp.trace_to(key)
            return QueryResult(
                query_id=qid, kind="AlwaysHolds", status="FAIL",
                states_explored=len(exp.states), trace=trace,
                findings=[Finding(Severity.ERROR, f"query:{qid}",
                                  f"'{text}' breaks: {_trace_str(trace)} ⇒ "
                                  f"{_offending_values(query.predicate, ctx)}")])
    if exp.capped:
        return _inconclusive(qid, "AlwaysHolds", exp)
    return QueryResult(query_id=qid, kind="AlwaysHolds", status="PASS",
                       states_explored=len(exp.states))


def _eval_no_dead_end(query, qid: str, exp: Exploration) -> QueryResult:
    text = query.label or _describe(query.goal)
    if exp.capped:
        return _inconclusive(qid, "NoDeadEnd", exp)

    goal_states = set()
    for key in exp.order:
        ctx = exp.states[key]
        refs = _collect_field_refs(query.goal)
        if any(r.entity_cls not in ctx for r in refs):
            continue
        try:
            if evaluate(query.goal, ctx):
                goal_states.add(key)
        except Exception:
            continue

    if not goal_states:
        return QueryResult(
            query_id=qid, kind="NoDeadEnd", status="FAIL", states_explored=len(exp.states),
            findings=[Finding(Severity.ERROR, f"query:{qid}",
                              f"goal '{text}' is not reachable at all")])

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
                query_id=qid, kind="NoDeadEnd", status="FAIL",
                states_explored=len(exp.states), trace=trace,
                findings=[Finding(Severity.ERROR, f"query:{qid}",
                                  f"dead end: after {_trace_str(trace)} the goal "
                                  f"'{text}' can no longer be reached")])
    return QueryResult(query_id=qid, kind="NoDeadEnd", status="PASS",
                       states_explored=len(exp.states))


def _eval_dead_actions(query, qid: str, exp: Exploration, spec: Spec) -> QueryResult:
    dead = sorted(a.id for a in spec.actions if a.id not in exp.fired)
    if not dead:
        return QueryResult(query_id=qid, kind="DeadActions", status="PASS",
                           states_explored=len(exp.states))
    if exp.capped:
        return _inconclusive(qid, "DeadActions", exp)
    return QueryResult(
        query_id=qid, kind="DeadActions", status="FAIL",
        states_explored=len(exp.states),
        findings=[Finding(Severity.ERROR, f"query:{qid}",
                          f"never enabled in any reachable state: {', '.join(dead)}")])


def _inconclusive(qid: str, kind: str, exp: Exploration) -> QueryResult:
    return QueryResult(
        query_id=qid, kind=kind, status="INCONCLUSIVE", states_explored=len(exp.states),
        findings=[Finding(Severity.WARNING, f"query:{qid}",
                          f"state space exceeded max_states={len(exp.states)} — "
                          f"add Bounds to numeric fields or raise max_states")])


def _offending_values(predicate, ctx: dict) -> str:
    parts = []
    for ref in _collect_field_refs(predicate):
        inst = ctx.get(ref.entity_cls)
        if inst is not None:
            parts.append(f"{ref.entity_cls.__name__}.{ref.field_name}="
                         f"{_value_str(getattr(inst, ref.field_name, None))}")
    return ", ".join(parts)
