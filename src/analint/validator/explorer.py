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
from itertools import product
from math import prod
from typing import Any

from analint.models.effect import Add, Set, Subtract
from analint.models.entity import FieldDescriptor, all_fields
from analint.models.initial import Initial
from analint.models.invariant import Invariant
from analint.models.predicate import Predicate
from analint.models.quantifier import BoundField, _Present
from analint.models.query import (
    AlwaysHolds,
    DeadActions,
    NoDeadEnd,
    Reachable,
    Unreachable,
)
from analint.models.root import Spec
from analint.models.scope import (
    InstanceField,
    InstanceRef,
    context_key_label,
    field_context_key,
    instance_context_key,
    is_field_ref,
    is_present,
)
from analint.reporter.base import Finding, InvariantResult, QueryResult, QueryStatus, Severity
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import evaluate
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
    roots: dict = dc_field(default_factory=dict)  # root key → 1-based initial index
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

    def root_of(self, key: StateKey) -> StateKey:
        while True:
            prev, _ = self.parents[key]
            if prev is None:
                return key
            key = prev

    def origin(self, key: StateKey) -> str:
        """A trace prefix naming the initial state, when there are several.

        A counterexample over an initial-state SET is ambiguous without its
        root (research/16): 'init #2 ⊢ vote(...)' pins the configuration.
        """
        if len(self.roots) <= 1:
            return ""
        return f"init #{self.roots[self.root_of(key)]} ⊢ "


# ── State helpers ──────────────────────────────────────────────────────────────


def state_key(ctx: dict) -> tuple:
    items = []
    for key in sorted(ctx, key=context_key_label):
        inst = ctx[key]
        cls = type(inst)
        if isinstance(key, InstanceRef):
            present = is_present(ctx, key)
            items.append((context_key_label(key), "@present", present))
            if not present:
                continue
        for f in sorted(all_fields(cls)):
            items.append((context_key_label(key), f, inst.__dict__.get(f)))
    return tuple(items)


def render_state(ctx: dict) -> dict:
    out = {}
    for key in sorted(ctx, key=context_key_label):
        inst = ctx[key]
        if isinstance(key, InstanceRef):
            present = is_present(ctx, key)
            out[f"{context_key_label(key)}.@present"] = _value_str(present)
            if not present:
                continue
        for f in sorted(all_fields(type(inst))):
            out[f"{context_key_label(key)}.{f}"] = _value_str(inst.__dict__.get(f))
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
    scopes_by_entity = {scope.entity_cls: scope for scope in spec.scopes}
    allowed_refs = {ref for scope in spec.scopes for ref in scope}
    for inst in given:
        context_key = instance_context_key(inst)
        if type(inst) in scopes_by_entity and not isinstance(context_key, InstanceRef):
            return None, (
                f"{type(inst).__name__} has a Scope — initial instances must be "
                f"created through a registered InstanceRef"
            )
        if isinstance(context_key, InstanceRef) and context_key not in allowed_refs:
            return None, f"{context_key!r} belongs to a Scope not registered in spec.scopes"
        ctx[context_key] = copy.copy(inst)

    missing: list[Any] = []
    scoped_classes = set(scopes_by_entity)
    for scope in spec.scopes:
        for ref in scope:
            if ref in ctx:
                continue
            try:
                ctx[ref] = ref()
            except TypeError:
                missing.append(ref)

    for cls in spec.entities:
        if cls in scoped_classes:
            continue
        if cls in ctx:
            continue
        try:
            ctx[cls] = cls()
        except TypeError:
            missing.append(cls)

    if missing:
        needed: set[Any] = set()
        for action in spec.actions:
            for pred in list(action.pre) + list(action.post):
                needed.update(field_context_key(r) for r in _collect_field_refs(pred))
            for e in action.effect:
                if isinstance(e, (Set, Subtract, Add)) and is_field_ref(e.field):
                    needed.add(field_context_key(e.field))
        for inv in spec.invariants:
            needed.update(field_context_key(r) for r in _collect_field_refs(inv.expression))
        blocked = [context_key_label(key) for key in missing if key in needed]
        if blocked:
            return None, (
                f"entities without full defaults need initial instances: "
                f"{', '.join(sorted(blocked))} — pass given=[...] in the query"
            )

    # the explored state must be hashable — reject unsupported field domains
    # up front instead of crashing inside state_key
    for context_key, inst in ctx.items():
        if isinstance(context_key, InstanceRef) and not is_present(ctx, context_key):
            continue
        for fname in all_fields(type(inst)):
            value = inst.__dict__.get(fname)
            try:
                hash(value)
            except TypeError:
                return None, (
                    f"{context_key_label(context_key)}.{fname} holds an unhashable "
                    f"value {value!r} — "
                    f"the engine supports scalar, enum, str and bool fields only"
                )
    return ctx, None


def build_initial_relation(
    spec: Spec,
    initial: Initial,
) -> tuple[list[dict] | None, str | None]:
    """Expand a declarative initial relation into finite BFS roots."""
    base, error = build_initial(spec, initial.given)
    if base is None:
        return None, error

    fields: list[FieldDescriptor | InstanceField] = []
    seen: set[tuple[Any, str]] = set()
    registered_scopes = set(spec.scopes)
    for item in initial.vary:
        if isinstance(item, BoundField):
            if item.variable.scope not in registered_scopes:
                return None, (
                    f"Bound '{item.variable.name}' uses Scope "
                    f"'{item.variable.scope.id or item.variable.scope.entity_cls.__name__}' "
                    f"not registered in spec.scopes"
                )
            expanded = [getattr(ref, item.field_name) for ref in item.variable.scope]
        elif is_field_ref(item):
            expanded = [item]
        else:
            return None, (f"Initial vary entry {item!r} is not a field reference or Bound field")
        for ref in expanded:
            marker = (field_context_key(ref), ref.field_name)
            if marker in seen:
                return None, f"Initial varies {context_key_label(marker[0])}.{marker[1]} twice"
            seen.add(marker)
            fields.append(ref)

    domains: list[list[Any]] = []
    for ref in fields:
        current = base.get(field_context_key(ref))
        current_value = getattr(current, ref.field_name, None) if current is not None else None
        domain, domain_error = _initial_field_domain(ref, current_value)
        if domain is None:
            return None, domain_error
        domains.append(domain)

    candidate_count = prod(len(domain) for domain in domains)
    if candidate_count > initial.max_candidates:
        return None, (
            f"Initial relation has {candidate_count} candidates, exceeding "
            f"max_candidates={initial.max_candidates} — narrow vary/domains or raise the limit"
        )

    roots: list[dict] = []
    root_keys: set[StateKey] = set()
    for values in product(*domains):
        ctx = {key: copy.copy(instance) for key, instance in base.items()}
        for ref, value in zip(fields, values, strict=True):
            key = field_context_key(ref)
            instance = ctx.get(key)
            if instance is None:
                return None, (
                    f"Initial varies {context_key_label(key)}.{ref.field_name}, "
                    f"but that entity is absent from the initial state"
                )
            if isinstance(key, InstanceRef) and not is_present(ctx, key):
                return None, (
                    f"Initial cannot vary field {context_key_label(key)}.{ref.field_name} "
                    f"because the entity is absent"
                )
            setattr(instance, ref.field_name, value)

        results: list[bool] = []
        for predicate in initial.where:
            refs = _collect_field_refs(predicate)
            missing = [field_context_key(ref) for ref in refs if field_context_key(ref) not in ctx]
            if missing:
                labels = ", ".join(sorted({context_key_label(key) for key in missing}))
                return None, f"Initial where predicate references missing entities: {labels}"
            try:
                results.append(evaluate(predicate, ctx))
            except Exception as exc:
                return None, (
                    f"Initial where evaluation error: {exc} (predicate: {_describe(predicate)})"
                )
        if not all(results):
            continue
        key = state_key(ctx)
        if key in root_keys:
            continue
        root_keys.add(key)
        roots.append(ctx)

    if not roots:
        return None, "Initial relation matches no states"
    return roots, None


def _initial_field_domain(
    ref: FieldDescriptor | InstanceField,
    current_value: Any,
) -> tuple[list[Any] | None, str | None]:
    descriptor = ref.descriptor if isinstance(ref, InstanceField) else ref
    spec = descriptor.spec
    if spec is not None and spec.values is not None:
        return list(spec.values), None

    default = descriptor.default
    annotation = _field_annotation(descriptor.entity_cls, descriptor.field_name)
    if annotation is bool or isinstance(default, bool) or isinstance(current_value, bool):
        return [False, True], None
    enum_cls = annotation if isinstance(annotation, type) and issubclass(annotation, Enum) else None
    if enum_cls is None and isinstance(default, Enum):
        enum_cls = type(default)
    if enum_cls is None and isinstance(current_value, Enum):
        enum_cls = type(current_value)
    if enum_cls is not None:
        return list(enum_cls), None

    if descriptor.lifecycle is not None:
        return sorted(descriptor.lifecycle.reachable_states(), key=repr), None

    if spec is not None:
        lower = spec.ge
        upper = spec.le
        if lower is None and isinstance(spec.gt, int):
            lower = spec.gt + 1
        if upper is None and isinstance(spec.lt, int):
            upper = spec.lt - 1
        if isinstance(lower, int) and isinstance(upper, int):
            return list(range(lower, upper + 1)), None

    return None, (
        f"Initial cannot infer a finite domain for "
        f"{context_key_label(field_context_key(ref))}.{ref.field_name} — "
        f"use bool/Enum, bounded integer Field(ge=..., le=...), "
        f"or Field(values=[...])"
    )


def _field_annotation(entity_cls: type, field_name: str) -> Any:
    for cls in entity_cls.__mro__:
        annotation = getattr(cls, "__annotations__", {}).get(field_name)
        if annotation is not None:
            return annotation
    return None


# ── Exploration ────────────────────────────────────────────────────────────────


def explore(spec: Spec, initial_ctxs: list[dict], max_states: int) -> Exploration:
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

    # Seed the BFS with every admissible initial state; identical roots merge
    # naturally through the state key (research/16: multi-root exploration).
    queue: list[StateKey] = []
    for index, ctx in enumerate(initial_ctxs, start=1):
        key0 = state_key(ctx)
        if key0 in exp.states:
            continue
        exp.states[key0] = ctx
        exp.order.append(key0)
        exp.parents[key0] = (None, None)
        exp.roots[key0] = index
        # An initial state that already violates an invariant is illegal: keep it
        # as a witness but do not explore from it, exactly as for any successor.
        if not _report_invariant_violations(spec, ctx, key0, exp):
            queue.append(key0)
    while queue:
        if len(exp.states) >= max_states:
            exp.capped = True
            break
        key = queue.pop(0)
        ctx = exp.states[key]

        for action in spec.actions:
            if action.id in exp.excluded:
                continue
            result = step(spec, action, ctx, trace=exp.trace_to(key))
            if result.entered:
                exp.fired.add(action.id)
            if result.outcome is Outcome.REJECTED:
                continue  # a guard disabled the action; its reason is a scenario concern
            if result.outcome is Outcome.DEFECT:
                for finding in result.findings:
                    exp.report_once(finding.severity, finding.location, finding.message)
                continue

            post = result.post_context
            if not action.effect:
                # an accepted effectless action is a self-loop with its post held true
                exp.edges.append((key, action.id, key))
                continue
            assert post is not None
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


def _report_invariant_violations(spec: Spec, ctx: dict, key: StateKey, exp: Exploration) -> bool:
    violated = False
    for inv in spec.invariants:
        refs = _collect_field_refs(inv.expression)
        if any(field_context_key(r) not in ctx for r in refs):
            continue
        try:
            ok = evaluate(inv.expression, ctx)
        except Exception as exc:
            # an unevaluable invariant is a model defect, not a pass: mark the
            # state illegal so it is kept as a witness but not expanded, matching
            # how the scenario runner treats the same error
            violated = True
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

    initial_sources = bool(query.given) + bool(query.given_any) + (query.initial is not None)
    if initial_sources > 1:
        return QueryResult(
            query_id=qid,
            kind=kind,
            status="FAIL",
            findings=[
                Finding(
                    Severity.ERROR,
                    f"query:{qid}",
                    "use exactly one of given=, given_any=, or initial=, not both/multiple",
                )
            ],
        )

    # A query with no initial source of its own starts from the spec's canonical
    # initial, so every check shares one state space unless it opts out.
    effective_initial = query.initial
    if initial_sources == 0 and spec.initial is not None:
        effective_initial = spec.initial

    initials: list[dict]
    if effective_initial is not None:
        built, error = build_initial_relation(spec, effective_initial)
        if built is None:
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
        initials = built
    else:
        initials = []
        for given in query.given_any or [query.given]:
            initial, error = build_initial(spec, given)
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
            initials.append(initial)

    root_keys = tuple(dict.fromkeys(state_key(ctx) for ctx in initials))
    cache_key = (root_keys, query.max_states)
    if cache_key not in cache:
        cache[cache_key] = explore(spec, initials, query.max_states)
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


def verify_invariants(spec: Spec, max_states: int = 10_000) -> list[InvariantResult]:
    """Verify every world invariant over the reachable states of the canonical
    model (``spec.initial``, or a single defaults-built root when it is None).

    This makes invariants a checked property of the model itself, not something
    only asserted when a user happens to write an ``AlwaysHolds`` query.
    """
    if not spec.invariants:
        return []

    if spec.initial is not None:
        initials, error = build_initial_relation(spec, spec.initial)
    else:
        root, error = build_initial(spec, [])
        initials = None if root is None else [root]

    if initials is None:
        # No canonical state space to check against — never a silent pass.
        return [
            InvariantResult(
                invariant_id=inv.id,
                label=inv.label or _describe(inv.expression),
                status=QueryStatus.NOT_CHECKED,
                findings=[
                    Finding(
                        Severity.WARNING,
                        f"invariant:{inv.id}",
                        f"not checked: could not build the canonical initial state "
                        f"({error}) — declare Spec(initial=...)",
                    )
                ],
            )
            for inv in spec.invariants
        ]

    exp = explore(spec, initials, max_states)
    return [_verify_one_invariant(inv, exp) for inv in spec.invariants]


def _verify_one_invariant(inv: Invariant, exp: Exploration) -> InvariantResult:
    label = inv.label or _describe(inv.expression)
    loc = f"invariant:{inv.id}"
    refs = _collect_field_refs(inv.expression)
    evaluated = False
    for key in exp.order:
        ctx = exp.states[key]
        if any(field_context_key(r) not in ctx for r in refs):
            continue  # not applicable in this state — its entities are absent
        evaluated = True
        try:
            ok = evaluate(inv.expression, ctx)
        except Exception as exc:
            return InvariantResult(
                invariant_id=inv.id,
                label=label,
                status=QueryStatus.FAIL,
                states_explored=len(exp.states),
                trace=exp.trace_to(key),
                findings=[Finding(Severity.ERROR, loc, f"evaluation error: {exc}")],
            )
        if not ok:
            return InvariantResult(
                invariant_id=inv.id,
                label=label,
                status=QueryStatus.FAIL,
                states_explored=len(exp.states),
                trace=exp.trace_to(key),
                findings=[
                    Finding(
                        Severity.ERROR,
                        loc,
                        f"invariant '{label}' is violated: {exp.origin(key)}"
                        f"{_trace_str(exp.trace_to(key))}",
                    )
                ],
            )

    if not evaluated:
        return InvariantResult(
            invariant_id=inv.id,
            label=label,
            status=QueryStatus.NOT_CHECKED,
            states_explored=len(exp.states),
            findings=[
                Finding(
                    Severity.WARNING,
                    loc,
                    "not checked: never evaluable over the canonical model "
                    "(its entities are absent in every reachable state)",
                )
            ],
        )

    if exp.capped:
        return InvariantResult(
            invariant_id=inv.id,
            label=label,
            status=QueryStatus.INCONCLUSIVE,
            states_explored=len(exp.states),
            findings=[
                Finding(
                    Severity.WARNING,
                    loc,
                    "inconclusive: exploration hit max_states before the state space was exhausted",
                )
            ],
        )

    return InvariantResult(
        invariant_id=inv.id, label=label, status=QueryStatus.PASS, states_explored=len(exp.states)
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
        if any(field_context_key(r) not in ctx for r in refs):
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
        origin = exp.origin(found)
        if expect_reachable:
            return QueryResult(
                query_id=qid,
                kind=kind,
                status="PASS",
                states_explored=len(exp.states),
                trace=trace,
                findings=[
                    Finding(
                        Severity.INFO,
                        f"query:{qid}",
                        f"'{text}' reachable: {origin}{_trace_str(trace)}",
                    ),
                    *_origin_findings(exp, found, qid),
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
                    f"'{text}' must be unreachable, but: {origin}{_trace_str(trace)}",
                ),
                *_origin_findings(exp, found, qid),
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
        if any(field_context_key(r) not in ctx for r in refs):
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
                        f"'{text}' breaks: {exp.origin(key)}{_trace_str(trace)} ⇒ "
                        f"{_offending_values(query.predicate, ctx)}",
                    ),
                    *_origin_findings(exp, key, qid),
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
        if any(field_context_key(r) not in ctx for r in refs):
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
                        f"dead end: after {exp.origin(key)}{_trace_str(trace)} the goal "
                        f"'{text}' can no longer be reached",
                    ),
                    *_origin_findings(exp, key, qid),
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


def _origin_findings(exp: Exploration, key: StateKey, qid: str) -> list[Finding]:
    """Describe the initial configuration a trace starts from (multi-root only)."""
    if len(exp.roots) <= 1:
        return []
    root = exp.root_of(key)
    rendered = ", ".join(f"{k}={v}" for k, v in render_state(exp.states[root]).items())
    return [Finding(Severity.INFO, f"query:{qid}", f"init #{exp.roots[root]}: {rendered}")]


def _offending_values(predicate: Predicate, ctx: dict) -> str:
    if isinstance(predicate, _Present) and isinstance(predicate.target, InstanceRef):
        return f"{predicate.target!r}.@present={is_present(ctx, predicate.target)!r}"
    parts = []
    for ref in _collect_field_refs(predicate):
        key = field_context_key(ref)
        inst = ctx.get(key)
        if inst is not None:
            parts.append(
                f"{context_key_label(key)}.{ref.field_name}="
                f"{_value_str(getattr(inst, ref.field_name, None))}"
            )
    return ", ".join(parts)


def _key_entity_cls(key: Any) -> type:
    return key.entity_cls if isinstance(key, InstanceRef) else key
