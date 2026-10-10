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
from array import array
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum
from functools import lru_cache
from itertools import product
from math import prod
from time import perf_counter
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
from analint.validator.slicing import Slice, SliceAnalysis
from analint.validator.state_checks import invariant_holds, invariant_is_applicable
from analint.validator.structural import _collect_field_refs, _describe

StateKey = bytes
Query = Reachable | Unreachable | AlwaysHolds | NoDeadEnd | DeadActions

# ── Exploration result ─────────────────────────────────────────────────────────


class Exploration:
    """The explored graph, stored compactly (research/36 R4).

    States are numbered in BFS order; a state is its key (``state_key``: a few
    bytes per entity) and its context is rebuilt from the key on demand rather
    than kept. Parents and edges are integer arrays. ``states``, ``order``,
    ``parents`` and ``edges`` keep the key-based read interface.
    """

    def __init__(self) -> None:
        self.keys: list[StateKey] = []  # index → key, in BFS order
        self.index: dict[StateKey, int] = {}  # key → index
        self.parent = array("i")  # index → parent index (-1 for a root)
        self.via = array("i")  # index → action code that reached it (-1 for a root)
        self.edge_src = array("i")
        self.edge_action = array("i")
        self.edge_dst = array("i")
        self.action_ids: list[str] = []  # action code → id
        self._action_codes: dict[str, int] = {}
        self.roots: dict = {}  # root key → 1-based initial index
        self.fired: set = set()  # action ids ever enabled
        self.findings: list = []  # violations met en route
        self.excluded: dict = {}  # action id → why it is not explorable
        self.capped = False
        self._seen: set = set()

    # ── building ─────────────────────────────────────────────────────────────

    def action_code(self, action_id: str) -> int:
        code = self._action_codes.get(action_id)
        if code is None:
            code = self._action_codes[action_id] = len(self.action_ids)
            self.action_ids.append(action_id)
        return code

    def add_state(self, key: StateKey, parent: int, via: int) -> int:
        idx = len(self.keys)
        self.keys.append(key)
        self.index[key] = idx
        self.parent.append(parent)
        self.via.append(via)
        return idx

    # ── key-based read interface ─────────────────────────────────────────────

    @property
    def order(self) -> list[StateKey]:
        return self.keys

    @property
    def states(self) -> _States:
        return _States(self)

    @property
    def parents(self) -> _Parents:
        return _Parents(self)

    @property
    def edges(self) -> _Edges:
        return _Edges(self)

    def report_once(self, severity: Severity, loc: str, message: str) -> None:
        """Deduplicated finding — a model error would otherwise repeat per state."""
        if (loc, message) in self._seen:
            return
        self._seen.add((loc, message))
        self.findings.append(Finding(severity, loc, message))

    def trace_to(self, key: StateKey) -> list[str]:
        return self._trace(self.index[key])

    def _trace(self, idx: int) -> list[str]:
        steps: list[str] = []
        while self.parent[idx] >= 0:
            steps.append(self.action_ids[self.via[idx]])
            idx = self.parent[idx]
        return list(reversed(steps))

    def root_of(self, key: StateKey) -> StateKey:
        idx = self.index[key]
        while self.parent[idx] >= 0:
            idx = self.parent[idx]
        return self.keys[idx]

    def origin(self, key: StateKey) -> str:
        """A trace prefix naming the initial state, when there are several.

        A counterexample over an initial-state SET is ambiguous without its
        root (research/16): 'init #2 ⊢ vote(...)' pins the configuration.
        """
        if len(self.roots) <= 1:
            return ""
        return f"init #{self.roots[self.root_of(key)]} ⊢ "


class _States(Mapping[StateKey, dict]):
    """key → context, rebuilt from the key (a fresh context on every read)."""

    def __init__(self, exp: Exploration) -> None:
        self._exp = exp

    def __getitem__(self, key: StateKey) -> dict:
        if key not in self._exp.index:
            raise KeyError(key)
        return decode_state(key)

    def __contains__(self, key: object) -> bool:
        return key in self._exp.index

    def __iter__(self) -> Iterator[StateKey]:
        return iter(self._exp.keys)

    def __len__(self) -> int:
        return len(self._exp.keys)


class _Parents(Mapping[StateKey, tuple]):
    """key → (parent key, action id); (None, None) for a root."""

    def __init__(self, exp: Exploration) -> None:
        self._exp = exp

    def __getitem__(self, key: StateKey) -> tuple:
        exp = self._exp
        idx = exp.index[key]
        if exp.parent[idx] < 0:
            return (None, None)
        return (exp.keys[exp.parent[idx]], exp.action_ids[exp.via[idx]])

    def __iter__(self) -> Iterator[StateKey]:
        return iter(self._exp.keys)

    def __len__(self) -> int:
        return len(self._exp.keys)


class _Edges(Sequence):
    """(source key, action id, target key) per explored transition."""

    def __init__(self, exp: Exploration) -> None:
        self._exp = exp

    def __len__(self) -> int:
        return len(self._exp.edge_src)

    def __getitem__(self, i: Any) -> Any:  # int → edge, slice → list of edges
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(len(self)))]
        exp = self._exp
        return (
            exp.keys[exp.edge_src[i]],
            exp.action_ids[exp.edge_action[i]],
            exp.keys[exp.edge_dst[i]],
        )

    def __eq__(self, other: object) -> bool:
        return list(self) == other if isinstance(other, list) else NotImplemented


# ── State helpers ──────────────────────────────────────────────────────────────


# Process-wide state layouts and their value tables. A key starts with its
# layout's id, so keys of different layouts (a slice and the whole model) can
# never compare equal. Each entity slot of a layout interns its value tuples:
# the key stores one small code per slot, and each distinct tuple is kept once.
_LAYOUT_IDS: dict[tuple, int] = {}
_LAYOUTS: list[tuple] = []  # layout id → layout
_SLOT_CODES: list[list[dict]] = []  # layout id → slot → value tuple → code
_SLOT_VALUES: list[list[list]] = []  # layout id → slot → code → value tuple
_SLOT_INSTANCES: list[list[dict]] = []  # layout id → slot → code → decoded instance


@lru_cache(maxsize=256)
def _state_layout(keys: tuple) -> tuple[int, tuple]:
    """(layout id, sorted (key, scoped, field names)) for a context's key set —
    the same for every state of one exploration, so computed once, not per state."""
    layout = tuple(
        (
            key,
            isinstance(key, InstanceRef),
            tuple(sorted(all_fields(key.entity_cls if isinstance(key, InstanceRef) else key))),
        )
        for key in sorted(keys, key=context_key_label)
    )
    layout_id = _LAYOUT_IDS.get(layout)
    if layout_id is None:
        layout_id = _LAYOUT_IDS[layout] = len(_LAYOUTS)
        _LAYOUTS.append(layout)
        _SLOT_CODES.append([{} for _ in layout])
        _SLOT_VALUES.append([[] for _ in layout])
        _SLOT_INSTANCES.append([{} for _ in layout])
    return layout_id, layout


_ESCAPE = 0xFFFF  # a code that does not fit 16 bits follows as two halves


def _put(out: array, code: int) -> None:
    if code < _ESCAPE:
        out.append(code)
    else:
        out.extend((_ESCAPE, code & 0xFFFF, code >> 16))


def state_key(ctx: dict) -> StateKey:
    """The state's identity: its layout id, then one code per entity slot.

    A slot's code names its interned value tuple — the field values in layout
    order, preceded by the presence flag for a scoped slot (an absent slot is
    just ``(False,)``). Equal values give equal tuples, so equality is exactly
    the field-by-field equality of the values (research/36 R4). Raises
    ``TypeError`` for an unhashable field value.
    """
    layout_id, layout = _state_layout(tuple(ctx))
    out = [layout_id]
    big = layout_id >= _ESCAPE
    for table, seen, (key, scoped, fields) in zip(
        _SLOT_CODES[layout_id], _SLOT_VALUES[layout_id], layout, strict=True
    ):
        values = ctx[key].__dict__
        if scoped:
            if values.get("_analint_present", True):
                value = (True, *map(values.get, fields))
            else:
                value = (False,)
        else:
            value = tuple(map(values.get, fields))
        code = table.get(value)
        if code is None:
            code = table[value] = len(seen)
            seen.append(value)
        if code >= _ESCAPE:  # a known code may be big too, not only a new one
            big = True
        out.append(code)
    if not big:  # 16-bit codes: one C-level pack
        return array("H", out).tobytes()
    escaped = array("H")
    for code in out:
        _put(escaped, code)
    return escaped.tobytes()


def _codes(key: StateKey) -> Sequence[int]:
    codes = memoryview(key).cast("H")
    if _ESCAPE not in codes:
        return codes
    out: list[int] = []
    i = 0
    while i < len(codes):
        if codes[i] == _ESCAPE:
            out.append(codes[i + 1] | codes[i + 2] << 16)
            i += 3
        else:
            out.append(codes[i])
            i += 1
    return out


def decode_state(key: StateKey) -> dict:
    """Rebuild the context a key was made from: a fresh dict of entity
    instances with the same field values and presence markers (absent slots
    read as ``Absent``).

    Instances are interned per distinct value tuple and shared between decoded
    contexts — treat them as read-only. Nothing mutates a state in place: the
    kernel copies an effect's targets before writing (copy-on-write, pinned by
    ``test_step_copies_targets_and_never_mutates_the_pre_state``)."""
    all_codes = _codes(key)
    layout_id, codes = all_codes[0], all_codes[1:]
    tuples = _SLOT_VALUES[layout_id]
    instances = _SLOT_INSTANCES[layout_id]
    ctx: dict = {}
    for slot, ((ctx_key, scoped, fields), code) in enumerate(
        zip(_LAYOUTS[layout_id], codes, strict=True)
    ):
        inst = instances[slot].get(code)
        if inst is None:
            inst = instances[slot][code] = _build_instance(
                ctx_key, scoped, fields, tuples[slot][code]
            )
        ctx[ctx_key] = inst
    return ctx


def _build_instance(ctx_key: Any, scoped: bool, fields: tuple, value: tuple) -> Any:
    inst = object.__new__(ctx_key.entity_cls if scoped else ctx_key)
    attrs = inst.__dict__
    if scoped:
        present = value[0]
        if present:
            attrs.update(zip(fields, value[1:], strict=True))
        else:
            attrs.update(dict.fromkeys(fields))  # an Absent snapshot
        attrs["_analint_instance_ref"] = ctx_key
        attrs["_analint_present"] = present
    else:
        attrs.update(zip(fields, value, strict=True))
    return inst


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


def explore(
    spec: Spec,
    initial_ctxs: list[dict],
    max_states: int,
    *,
    root_numbers: list[int] | None = None,
    inert_roots: frozenset[int] = frozenset(),
) -> Exploration:
    """BFS from ``initial_ctxs``. ``root_numbers`` keeps the 1-based labels of a
    subset of a larger root set (slices); roots at ``inert_roots`` positions
    are kept as states but not expanded (illegal in the full model)."""
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
    # The frontier carries its contexts; a state's context is dropped once it
    # is expanded and rebuilt from its key if a query needs it later.
    queue: deque[tuple[int, dict]] = deque()
    for pos, ctx in enumerate(initial_ctxs):
        index = root_numbers[pos] if root_numbers is not None else pos + 1
        key0 = state_key(ctx)
        if key0 in exp.index:
            continue
        idx0 = exp.add_state(key0, -1, -1)
        exp.roots[key0] = index
        # An initial state that already violates an invariant is illegal: keep it
        # as a witness but do not explore from it, exactly as for any successor.
        if not _report_invariant_violations(spec, ctx, key0, exp) and pos not in inert_roots:
            queue.append((idx0, ctx))
    codes = [exp.action_code(action.id) for action in spec.actions]
    index_get = exp.index.get
    add_src, add_act, add_dst = exp.edge_src.append, exp.edge_action.append, exp.edge_dst.append
    while queue:
        if len(exp.keys) >= max_states:
            exp.capped = True
            break
        idx, ctx = queue.popleft()

        for action, code in zip(spec.actions, codes, strict=True):
            if action.id in exp.excluded:
                continue
            result = step(spec, action, ctx, explain=False)
            if result.entered:
                exp.fired.add(action.id)
            if result.outcome is Outcome.REJECTED:
                continue  # a guard disabled the action; its reason is a scenario concern
            if result.outcome is Outcome.DEFECT:
                # step is pure: re-run it with the trace only now that a defect
                # needs one (building the trace for every step was a hot spot)
                for finding in step(spec, action, ctx, trace=exp._trace(idx)).findings:
                    exp.report_once(finding.severity, finding.location, finding.message)
                continue

            post = result.post_context
            if not action.effect:
                # an accepted effectless action is a self-loop with its post held true
                add_src(idx)
                add_act(code)
                add_dst(idx)
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
            known = index_get(k2)
            idx2 = exp.add_state(k2, idx, code) if known is None else known
            add_src(idx)
            add_act(code)
            add_dst(idx2)
            if known is not None:
                continue
            if _report_invariant_violations(spec, post, k2, exp):
                continue  # illegal state: reported, not expanded further
            queue.append((idx2, post))

    return exp


def _report_invariant_violations(spec: Spec, ctx: dict, key: StateKey, exp: Exploration) -> bool:
    violated = False
    for inv in spec.invariants:
        if not invariant_is_applicable(inv, ctx):
            continue  # a referenced entity/Scope slot is absent — not applicable here
        try:
            ok = invariant_holds(inv, ctx)
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


def resolve_query_initials(query: Query, spec: Spec) -> tuple[list[dict] | None, str | None]:
    """The initial contexts a query explores from — its own ``given``/``given_any``/
    ``initial``, or the spec's canonical initial when it declares none. Returns
    ``(initials, None)`` or ``(None, error)``. The single interpretation of a
    query's initial source, shared by ``run_query`` and the exploration service.
    """
    initial_sources = bool(query.given) + bool(query.given_any) + (query.initial is not None)
    if initial_sources > 1:
        return None, "use exactly one of given=, given_any=, or initial=, not both/multiple"

    # A query with no initial source of its own starts from the spec's canonical
    # initial, so every check shares one state space unless it opts out.
    effective_initial = query.initial
    if initial_sources == 0 and spec.initial is not None:
        effective_initial = spec.initial

    if effective_initial is not None:
        built, error = build_initial_relation(spec, effective_initial)
        if built is None:
            return None, error or "could not build the initial state"
        return built, None

    initials: list[dict] = []
    for given in query.given_any or [query.given]:
        initial, error = build_initial(spec, given)
        if initial is None:
            return None, error or "could not build the initial state"
        initials.append(initial)
    return initials, None


def run_query(
    query: Query,
    spec: Spec,
    cache: dict,
    *,
    max_states: int | None = None,
    analysis: SliceAnalysis | None = None,
    explorations: dict[str, Exploration] | None = None,
) -> QueryResult:
    """``max_states`` overrides the query's own budget (``check --max-states``).
    With ``analysis`` the query is checked on its slice (research/34 §5).
    ``explorations``, when given, receives the exploration the result was
    decided on (by query id), so a trace replays exactly the check.
    Timing includes root construction, action coverage, exploration and query
    evaluation performed by this call; cached work is not charged again."""
    started = perf_counter()
    result = _run_query(
        query, spec, cache, max_states=max_states, analysis=analysis, explorations=explorations
    )
    result.elapsed_ms = (perf_counter() - started) * 1000
    return result


def _run_query(
    query: Query,
    spec: Spec,
    cache: dict,
    *,
    max_states: int | None,
    analysis: SliceAnalysis | None,
    explorations: dict[str, Exploration] | None = None,
) -> QueryResult:
    qid = query.id or type(query).__name__
    explorations = {} if explorations is None else explorations
    kind = type(query).__name__

    initials, error = resolve_query_initials(query, spec)
    if initials is None:
        return QueryResult(
            query_id=qid,
            kind=kind,
            status="FAIL",
            findings=[Finding(Severity.ERROR, f"query:{qid}", error or "bad initial state")],
        )

    budget = max_states or query.max_states
    if not isinstance(query, (Reachable, Unreachable, AlwaysHolds, NoDeadEnd, DeadActions)):
        return QueryResult(
            query_id=qid,
            kind=kind,
            status="FAIL",
            findings=[Finding(Severity.ERROR, f"query:{qid}", f"unknown query type {kind}")],
        )
    if analysis is not None:
        # the full exploration of these roots would surface every action's
        # defects; the per-action slices do the same and decide DeadActions
        # invariants were proven from the canonical roots only (SliceAnalysis)
        canonical = not (query.given or query.given_any or query.initial is not None)
        per_action = cover_actions(analysis, initials, budget, cache, canonical=canonical)
        if isinstance(query, DeadActions):
            return _eval_dead_actions_sliced(qid, spec, per_action)
        if isinstance(query, NoDeadEnd):  # a closed lock creates dead ends
            piece = analysis.predicate_slice(query.goal, locks=True, canonical=canonical)
        else:
            piece = analysis.predicate_slice(query.predicate, canonical=canonical)
        exp, used = explore_slice(analysis, piece, initials, budget, cache)
        explorations[qid] = exp
        result = _evaluate(query, qid, exp, spec)
        result.slice = used.summary()
        return result
    exp = explore_cached(spec, initials, budget, cache)
    explorations[qid] = exp
    return _evaluate(query, qid, exp, spec)


def _evaluate(query: Query, qid: str, exp: Exploration, spec: Spec) -> QueryResult:
    if isinstance(query, Reachable):
        return _eval_reachable(query, qid, exp, expect_reachable=True)
    if isinstance(query, Unreachable):
        return _eval_reachable(query, qid, exp, expect_reachable=False)
    if isinstance(query, AlwaysHolds):
        return _eval_always(query, qid, exp)
    if isinstance(query, NoDeadEnd):
        return _eval_no_dead_end(query, qid, exp)
    return _eval_dead_actions(query, qid, exp, spec)


def explore_slice(
    analysis: SliceAnalysis,
    piece: Slice,
    initials: list[dict],
    max_states: int,
    cache: dict,
    *,
    reuse_superset: bool = False,
) -> tuple[Exploration, Slice]:
    """Explore one slice (research/34 §5); returns the exploration and the
    slice it actually covers. A complete exploration of a closed superset is
    exact for every slice inside it; ``reuse_superset`` answers from it instead
    of exploring (used by the per-action coverage — a property reports its own,
    smallest slice)."""
    if piece.vars is None:
        return explore_cached(analysis.spec, initials, max_states, cache), piece
    explored = analysis.explored.setdefault((analysis.roots_key(initials), max_states), [])
    for used, exp in explored:
        if used.key == piece.key or (
            reuse_superset
            and not exp.capped
            and piece.vars <= used.vars
            # more variables need not mean more actions: an effectless action,
            # or a writer that only switches a flag off, joins only its own slice
            and {id(a) for a in piece.actions} <= {id(a) for a in used.actions}
            and analysis.is_exact(used)
        ):
            return exp, used
    roots, numbers, inert = analysis.project_roots(piece, initials)
    exp = explore(
        analysis.sliced_spec(piece), roots, max_states, root_numbers=numbers, inert_roots=inert
    )
    explored.append((piece, exp))
    return exp, piece


def cover_actions(
    analysis: SliceAnalysis,
    initials: list[dict],
    max_states: int,
    cache: dict,
    *,
    canonical: bool,
) -> dict[int, Exploration]:
    """Every action explored in its own slice from these roots — the sliced
    counterpart of one full exploration: it surfaces each action's defects and
    decides its fireability. Keyed by id(action)."""
    key = (analysis.roots_key(initials), max_states, canonical)
    if key not in analysis.covered:
        # largest slices first, so the nested ones reuse their explorations
        pieces = [
            (action, analysis.action_slice(action, canonical=canonical))
            for action in analysis.spec.actions
        ]
        pieces.sort(key=lambda item: -len(item[1].vars or ()))
        analysis.covered[key] = {
            id(action): explore_slice(
                analysis, piece, initials, max_states, cache, reuse_superset=True
            )[0]
            for action, piece in pieces
        }
    return analysis.covered[key]


def explore_cached(spec: Spec, initials: list[dict], max_states: int, cache: dict) -> Exploration:
    """One exploration per (root set, budget) within a validate() run: the
    canonical invariant check and default-source queries share a state space."""
    root_keys = tuple(dict.fromkeys(state_key(ctx) for ctx in initials))
    cache_key = (root_keys, max_states)
    if cache_key not in cache:
        cache[cache_key] = explore(spec, initials, max_states)
    return cache[cache_key]


def build_canonical_initials(spec: Spec) -> tuple[list[dict] | None, str | None]:
    """The model's canonical initial states: ``spec.initial`` expanded, or a
    single defaults-built root when it is None. Returns ``(None, error)`` when
    the relation cannot be built. Built once per run for canonical-initial
    validation and invariant verification. (Default-source queries rebuild
    equivalent roots in ``run_query``; the exploration itself is shared through
    ``explore_cached``.)"""
    if spec.initial is not None:
        return build_initial_relation(spec, spec.initial)
    root, error = build_initial(spec, [])
    return ([root] if root is not None else None), error


def verify_invariants(
    spec: Spec,
    initials: list[dict] | None,
    *,
    build_error: str | None = None,
    max_states: int = 10_000,
    cache: dict | None = None,
    analysis: SliceAnalysis | None = None,
    explorations: dict[str, Exploration] | None = None,
) -> tuple[list[InvariantResult], Exploration | None]:
    """Verify every world invariant over the reachable states of the canonical
    model. ``initials`` is the pre-built canonical state set (see
    ``build_canonical_initials``); ``None`` means it could not be built.

    Returns the per-invariant results AND the canonical ``Exploration`` (None
    when it could not be built), so the caller can surface the same transition
    defects the exploration found — dropping them would hide a model defect
    behind a green invariant. This makes invariants a checked property of the
    model itself, not something only asserted when a user happens to write an
    ``AlwaysHolds`` query.

    ``explorations``, when given, receives the exploration each final result
    was decided on (by invariant id), so a trace replays exactly the check.
    """
    explorations = {} if explorations is None else explorations
    if not spec.invariants:
        return [], None

    if initials is None:
        # No canonical state space to check against — never a silent pass.
        hint = " — declare Spec(initial=...)" if spec.initial is None else ""
        results = [
            InvariantResult(
                invariant_id=inv.id,
                label=inv.label or _describe(inv.expression),
                status=QueryStatus.NOT_CHECKED,
                findings=[
                    Finding(
                        Severity.WARNING,
                        f"invariant:{inv.id}",
                        f"not checked: could not build the canonical initial state "
                        f"({build_error}){hint}",
                    )
                ],
            )
            for inv in spec.invariants
        ]
        return results, None

    cache = {} if cache is None else cache
    if analysis is not None:
        # Phase 1: each invariant on its unconstrained slice. That model prunes
        # less than the whole one, so a PASS there is final — and makes the
        # invariant trusted: it never prunes, other slices need not include it.
        pending = []
        for inv in spec.invariants:
            started = perf_counter()
            exp, used = explore_slice(
                analysis,
                analysis.invariant_slice(inv, unconstrained=True),
                initials,
                max_states,
                cache,
            )
            pending.append((inv, exp, used, (perf_counter() - started) * 1000))
            explorations[inv.id] = exp
        # invariants sharing an exploration are checked in one pass over it
        verdicts = _verify_grouped([(inv, exp) for inv, exp, _, _ in pending])
        checked = []
        for (inv, _, used, explore_ms), result in zip(pending, verdicts, strict=True):
            result.elapsed_ms = (result.elapsed_ms or 0.0) + explore_ms
            if result.status == QueryStatus.PASS:
                analysis.trusted.add(id(inv))
            checked.append((inv, result, used))
        # Phase 2: a FAIL is true of the whole model only on an exact slice.
        results = []
        for inv, result, used in checked:
            if result.status == QueryStatus.FAIL and not analysis.is_exact(used):
                elapsed_ms = result.elapsed_ms or 0.0
                started = perf_counter()
                exp, used = explore_slice(
                    analysis, analysis.invariant_slice(inv), initials, max_states, cache
                )
                result = _verify_one_invariant(inv, exp)
                explorations[inv.id] = exp
                result.elapsed_ms = elapsed_ms + (perf_counter() - started) * 1000
            result.slice = used.summary()
            results.append(result)
        # defects parity with the full canonical exploration (see cover_actions)
        cover_actions(analysis, initials, max_states, cache, canonical=True)
        return results, None
    # Charge the shared exploration to the first invariant that requests it.
    started = perf_counter()
    exp = explore_cached(spec, initials, max_states, cache)
    explore_ms = (perf_counter() - started) * 1000
    results = _verify_invariants(spec.invariants, exp)
    results[0].elapsed_ms = (results[0].elapsed_ms or 0.0) + explore_ms
    for inv in spec.invariants:
        explorations[inv.id] = exp
    return results, exp


def _verify_one_invariant(inv: Invariant, exp: Exploration) -> InvariantResult:
    return _verify_invariants([inv], exp)[0]


def _verify_grouped(pairs: list[tuple[Invariant, Exploration]]) -> list[InvariantResult]:
    """Verify (invariant, exploration) pairs, scanning each exploration once."""
    groups: dict[int, list[int]] = {}
    for i, (_, exp) in enumerate(pairs):
        groups.setdefault(id(exp), []).append(i)
    results: list = [None] * len(pairs)
    for members in groups.values():
        exp = pairs[members[0]][1]
        verdicts = _verify_invariants([pairs[i][0] for i in members], exp)
        for i, result in zip(members, verdicts, strict=True):
            results[i] = result
    return results


def _verify_invariants(invs: list[Invariant], exp: Exploration) -> list[InvariantResult]:
    """One pass over the explored states (each rebuilt from its key once) for
    all ``invs``; each invariant stops at its first violation in BFS order.
    ``elapsed_ms`` is each invariant's own evaluation time; the shared
    decoding is charged to the first."""
    failed: dict[int, InvariantResult] = {}
    evaluated: set[int] = set()
    spent = [0.0] * len(invs)
    for key in exp.order:
        if len(failed) == len(invs):
            break
        started = perf_counter()
        ctx = decode_state(key)  # keys of exp.order are all explored
        spent[0] += perf_counter() - started
        for i, inv in enumerate(invs):
            if i in failed:
                continue
            started = perf_counter()
            outcome = _check_invariant_at(inv, exp, key, ctx)
            spent[i] += perf_counter() - started
            if outcome is None:
                continue
            evaluated.add(i)
            if isinstance(outcome, InvariantResult):
                failed[i] = outcome
    results = [
        failed[i] if i in failed else _invariant_outcome(inv, exp, i in evaluated)
        for i, inv in enumerate(invs)
    ]
    for result, seconds in zip(results, spent, strict=True):
        result.elapsed_ms = seconds * 1000
    return results


def _check_invariant_at(
    inv: Invariant, exp: Exploration, key: StateKey, ctx: dict
) -> InvariantResult | bool | None:
    """None — not applicable here; True — holds; a FAIL ``InvariantResult``
    otherwise."""
    if not invariant_is_applicable(inv, ctx):
        return None  # presence-aware: a referenced entity/slot is absent here
    try:
        ok = invariant_holds(inv, ctx)
    except Exception as exc:
        return _invariant_failure(inv, exp, key, f"evaluation error: {exc}")
    if ok:
        return True
    label = inv.label or _describe(inv.expression)
    return _invariant_failure(
        inv,
        exp,
        key,
        f"invariant '{label}' is violated: {exp.origin(key)}{_trace_str(exp.trace_to(key))}",
    )


def _invariant_failure(
    inv: Invariant, exp: Exploration, key: StateKey, message: str
) -> InvariantResult:
    return InvariantResult(
        invariant_id=inv.id,
        label=inv.label or _describe(inv.expression),
        status=QueryStatus.FAIL,
        states_explored=len(exp.states),
        trace=exp.trace_to(key),
        witness_key=key,
        findings=[Finding(Severity.ERROR, f"invariant:{inv.id}", message)],
    )


def _invariant_outcome(inv: Invariant, exp: Exploration, evaluated: bool) -> InvariantResult:
    """The verdict of an invariant that no explored state violated."""
    label = inv.label or _describe(inv.expression)
    loc = f"invariant:{inv.id}"
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

    if exp.excluded:
        # Some actions were not explorable (e.g. event-payload preconditions are
        # outside the engine's state model). A no-counterexample run over a
        # partial transition relation cannot claim PASS.
        excluded = ", ".join(sorted(exp.excluded))
        return InvariantResult(
            invariant_id=inv.id,
            label=label,
            status=QueryStatus.INCONCLUSIVE,
            states_explored=len(exp.states),
            findings=[
                Finding(
                    Severity.WARNING,
                    loc,
                    f"inconclusive: held in every explored state, but actions "
                    f"[{excluded}] were excluded from exploration, so the "
                    f"transition relation is incomplete",
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
        ctx = decode_state(key)  # keys of exp.order are all explored
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
                witness_key=found,
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
            witness_key=found,
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
        ctx = decode_state(key)  # keys of exp.order are all explored
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
                witness_key=key,
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
        ctx = decode_state(key)  # keys of exp.order are all explored
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

    # backward reachability over integer state indices (no key tuples per edge)
    reverse: dict[int, list[int]] = {}
    for src, dst in zip(exp.edge_src, exp.edge_dst, strict=True):
        reverse.setdefault(dst, []).append(src)
    co_reachable = {exp.index[key] for key in goal_states}
    stack = list(co_reachable)
    while stack:
        node = stack.pop()
        for prev in reverse.get(node, ()):
            if prev not in co_reachable:
                co_reachable.add(prev)
                stack.append(prev)

    for idx, key in enumerate(exp.order):  # BFS order → shortest trace to the first dead end
        if idx not in co_reachable:
            trace = exp.trace_to(key)
            return QueryResult(
                query_id=qid,
                kind="NoDeadEnd",
                status="FAIL",
                states_explored=len(exp.states),
                trace=trace,
                witness_key=key,
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


def _eval_dead_actions_sliced(
    qid: str, spec: Spec, per_action: dict[int, Exploration]
) -> QueryResult:
    """DeadActions over per-action slices: an action is dead only if its own
    slice was exhausted without firing it; a capped slice decides nothing."""
    dead: list[str] = []
    undecided: list[str] = []
    excluded: dict[str, str] = {}
    for action in spec.actions:
        exp = per_action[id(action)]
        if action.id in exp.excluded:
            excluded[action.id] = exp.excluded[action.id]
        elif action.id not in exp.fired:
            (undecided if exp.capped else dead).append(action.id)
    distinct = {id(exp): exp for exp in per_action.values()}.values()
    explored = sum(len(exp.states) for exp in distinct)
    findings = []
    if dead:
        findings.append(
            Finding(
                Severity.ERROR,
                f"query:{qid}",
                f"never enabled in any reachable state: {', '.join(sorted(dead))}",
            )
        )
    if undecided:
        findings.append(
            Finding(
                Severity.WARNING,
                f"query:{qid}",
                f"not decided — their slices exceeded max_states: {', '.join(sorted(undecided))}",
            )
        )
    findings.extend(
        Finding(
            Severity.INFO,
            f"query:{qid}",
            f"not assessed (excluded from exploration): {aid} — {reason}",
        )
        for aid, reason in sorted(excluded.items())
    )
    status = "FAIL" if dead else "INCONCLUSIVE" if undecided else "PASS"
    return QueryResult(
        query_id=qid,
        kind="DeadActions",
        status=status,
        states_explored=explored,
        findings=findings,
        slice={"per_action": True, "slices": len(distinct)},
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
