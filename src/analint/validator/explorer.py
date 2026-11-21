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
from collections import Counter, deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum
from functools import lru_cache
from itertools import product
from math import prod
from time import perf_counter
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Create, Delete, Set, Subtract
from analint.models.entity import FieldDescriptor, all_fields
from analint.models.expr import _AddExpr, _FloorDivExpr, _MulExpr, _SubExpr
from analint.models.initial import Initial
from analint.models.invariant import Invariant
from analint.models.predicate import Predicate
from analint.models.quantifier import BoundField, _Present, _Sum
from analint.models.query import (
    AlwaysHolds,
    DeadActions,
    NoDeadEnd,
    Reachable,
    Unreachable,
    query_budget,
)
from analint.models.root import Spec
from analint.models.scope import (
    Absent,
    InstanceField,
    InstanceRef,
    context_key_label,
    field_context_key,
    instance_context_key,
    is_field_ref,
    is_present,
)
from analint.reporter.base import Code, Finding, InvariantResult, QueryResult, QueryStatus, Severity
from analint.validator.kernel import Outcome, build_plan, step
from analint.validator.rule_checker import compile_predicate, evaluate
from analint.validator.slicing import (
    PRESENT,
    Slice,
    SliceAnalysis,
    Var,
    _action_writes,
    _pred_vars,
    _target_key,
    _Unsliceable,
)
from analint.validator.state_checks import InvariantPlan
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

    def __init__(self, *, store_edges: bool = True) -> None:
        self._edges_stored = store_edges
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
        self.multiple_roots = False  # replay carries one path from a multi-root relation
        self.invalid_roots: set[int] = set()  # state indices retained but not expanded
        self.fired: set = set()  # action ids ever enabled
        self.findings: list = []  # violations met en route
        # Internal provenance for invariant diagnostics, including every state
        # represented by a deduplicated evaluation error. Not part of Finding JSON.
        self.finding_states: dict[int, set[int]] = {}  # finding index → state indices
        self.excluded: dict = {}  # action id → why it is not explorable
        self.capped = False
        self.growing: list[str] = []  # on a cap: numeric fields with no bound
        self._seen: dict[tuple, int] = {}
        self._released_count: int | None = None
        self._root_origins: dict[int, tuple[StateKey, ...]] = {}
        self._query_context_cache: tuple[int, frozenset, dict[bytes, dict]] | None = None

    @property
    def state_count(self) -> int:
        return len(self.keys) if self._released_count is None else self._released_count

    def root_origins(self, finding: int) -> tuple[StateKey, ...]:
        """Return the origins only when every instance of the finding is at a root."""
        if self._released_count is not None:
            return self._root_origins.get(finding, ())
        states = self.finding_states.get(finding, ())
        return (
            tuple(self.keys[i] for i in states) if all(self.parent[i] < 0 for i in states) else ()
        )

    def release_graph(self) -> None:
        """Keep the diagnostics and counts needed for report assembly."""
        if self._released_count is not None:
            return
        self._root_origins = {i: self.root_origins(i) for i in self.finding_states}
        self._released_count = len(self.keys)
        self.keys.clear()
        self._query_context_cache = None
        self.index.clear()
        self.roots.clear()
        self.parent = array("i")
        self.via = array("i")
        self.discard_edges()
        self.finding_states.clear()
        self.invalid_roots.clear()
        self._seen.clear()

    def discard_edges(self) -> None:
        self._edges_stored = False
        self.edge_src = array("i")
        self.edge_action = array("i")
        self.edge_dst = array("i")

    def _require_graph(self) -> None:
        assert self._released_count is None, "exploration graph was released"

    def _require_edges(self) -> None:
        self._require_graph()
        assert self._edges_stored, "exploration edges were not stored"

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
        self._require_graph()
        return self.keys

    @property
    def states(self) -> _States:
        self._require_graph()
        return _States(self)

    @property
    def parents(self) -> _Parents:
        self._require_graph()
        return _Parents(self)

    @property
    def edges(self) -> _Edges:
        return _Edges(self)

    def report_once(
        self, severity: Severity, loc: str, message: str, code: Code, *, state: int | None = None
    ) -> None:
        """Deduplicated finding — a model error would otherwise repeat per state."""
        identity = (loc, message)
        index = self._seen.get(identity)
        if index is None:
            index = self._seen[identity] = len(self.findings)
            self.findings.append(Finding(severity, loc, message, code))
        if state is not None:
            self.finding_states.setdefault(index, set()).add(state)

    def trace_to(self, key: StateKey) -> list[str]:
        self._require_graph()
        return self._trace(self.index[key])

    def _trace(self, idx: int) -> list[str]:
        steps: list[str] = []
        while self.parent[idx] >= 0:
            steps.append(self.action_ids[self.via[idx]])
            idx = self.parent[idx]
        return list(reversed(steps))

    def root_of(self, key: StateKey) -> StateKey:
        self._require_graph()
        idx = self.index[key]
        while self.parent[idx] >= 0:
            idx = self.parent[idx]
        return self.keys[idx]

    def origin(self, key: StateKey) -> str:
        """A trace prefix naming the initial state, when there are several.

        A counterexample over an initial-state SET is ambiguous without its
        root (research/16): 'init #2 ⊢ vote(...)' pins the configuration.
        """
        self._require_graph()
        if len(self.roots) <= 1 and not self.multiple_roots:
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
        exp._require_edges()
        self._exp = exp

    def __len__(self) -> int:
        self._exp._require_edges()
        return len(self._exp.edge_src)

    def __getitem__(self, i: Any) -> Any:  # int → edge, slice → list of edges
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(len(self)))]
        exp = self._exp
        exp._require_edges()
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
_PROJECTED_LAYOUTS: set[int] = set()
_SLOT_CODES: list[list[dict]] = []  # layout id → slot → value tuple → code
_SLOT_VALUES: list[list[list]] = []  # layout id → slot → code → value tuple
_SLOT_INSTANCES: list[list[dict]] = []  # layout id → slot → code → decoded instance


@lru_cache(maxsize=256)
def _state_layout(keys: tuple, projection: frozenset[Var] | None = None) -> tuple[int, tuple]:
    """(layout id, sorted (key, scoped, field names)) for a context's key set —
    the same for every state of one exploration, so computed once, not per state."""
    layout = tuple(
        (
            key,
            isinstance(key, InstanceRef),
            tuple(
                name
                for name in sorted(all_fields(_key_entity_cls(key)))
                if projection is None or (key, name) in projection
            ),
        )
        for key in sorted(keys, key=context_key_label)
    )
    identity = (layout, projection is not None)
    layout_id = _LAYOUT_IDS.get(identity)
    if layout_id is None:
        layout_id = _LAYOUT_IDS[identity] = len(_LAYOUTS)
        if projection is not None:
            _PROJECTED_LAYOUTS.add(layout_id)
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
    return _key_in_layout(ctx, *_state_layout(tuple(ctx)))


def _key_in_layout(ctx: dict, layout_id: int, layout: tuple) -> StateKey:
    out = [layout_id]
    for slot, (key, scoped, fields) in enumerate(layout):
        out.append(_intern(layout_id, slot, _slot_value(ctx[key], scoped, fields)))
    return _pack(out)


def _slot_value(instance: Any, scoped: bool, fields: tuple) -> tuple:
    values = instance.__dict__
    if scoped:
        if values.get("_analint_present", True):
            return (True, *map(values.get, fields))
        return (False,)
    return tuple(map(values.get, fields))


def _successor_key(parent: list[int], post: dict, changed_slots: tuple) -> StateKey:
    codes = parent.copy()
    layout_id = codes[0]
    for slot, (key, scoped, fields) in changed_slots:
        codes[slot + 1] = _intern(layout_id, slot, _slot_value(post[key], scoped, fields))
    return _pack(codes)


def _root_signature(ctx: dict) -> tuple:
    """State equality without interning values ahead of BFS."""
    return tuple(
        (
            key,
            (
                (True, *(inst.__dict__.get(f) for f in all_fields(key.entity_cls)))
                if is_present(ctx, key)
                else (False,)
            )
            if isinstance(key, InstanceRef)
            else tuple(inst.__dict__.get(f) for f in all_fields(key)),
        )
        for key, inst in sorted(ctx.items(), key=lambda item: context_key_label(item[0]))
    )


def _intern(layout_id: int, slot: int, value: tuple) -> int:
    """The code of a slot's value tuple, interning it when new."""
    table = _SLOT_CODES[layout_id][slot]
    # Erasure can merge concrete states whose numerically equal values
    # have different arithmetic behavior (for example, int and float).
    identity = (
        tuple((type(v), v.hex() if type(v) is float else v) for v in value)
        if layout_id in _PROJECTED_LAYOUTS
        else value
    )
    code = table.get(identity)
    if code is None:
        seen = _SLOT_VALUES[layout_id][slot]
        code = table[identity] = len(seen)
        seen.append(value)
    return code


def _pack(codes: list[int]) -> StateKey:
    if max(codes) < _ESCAPE:  # 16-bit codes: one C-level pack
        return array("H", codes).tobytes()
    escaped = array("H")
    for code in codes:
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
            if not scope.initially_present:
                ctx[ref] = Absent(ref)
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
    *,
    intern: bool = True,
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
    root_keys = set()
    key_of = state_key if intern else _root_signature
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
        key = key_of(ctx)
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


# The on-disk exploration memo in use (``exploration_cache.use_store``), if any.
_STORE: Any = None


def explore(
    spec: Spec,
    initial_ctxs: list[dict],
    max_states: int,
    *,
    root_numbers: list[int] | None = None,
    inert_roots: frozenset[int] = frozenset(),
    store_edges: bool = True,
    projection: frozenset[Var] | None = None,
) -> Exploration:
    """BFS from ``initial_ctxs``. ``root_numbers`` keeps the 1-based labels of a
    subset of a larger root set (slices); roots at ``inert_roots`` positions
    are kept as states but not expanded (illegal in the full model). A pure
    function of its arguments, so an exploration store may memoise it."""
    if _STORE is not None:
        # The disk format always contains the complete edge stream.
        exp = _STORE.explore(
            _explore,
            spec,
            initial_ctxs,
            max_states,
            root_numbers,
            inert_roots,
            **({"projection": projection} if projection is not None else {}),
        )
        if not store_edges:
            exp.discard_edges()
        return exp
    return _explore(
        spec,
        initial_ctxs,
        max_states,
        root_numbers,
        inert_roots,
        store_edges,
        **({"projection": projection} if projection is not None else {}),
    )


class _Frontier(deque):
    """Share the context's keys across descendants and keep its exact values.

    State keys intern equal values, which can have different types (for
    example, 1 and 1.0). The kernel must see the original state values.
    """

    def push(self, idx: int, ctx: dict, rejected: int, keys: tuple) -> None:
        self.append((idx, tuple(ctx.values()), rejected, keys))

    def pop_state(self) -> tuple[int, dict, int, tuple]:
        idx, values, rejected, keys = self.popleft()
        return idx, dict(zip(keys, values, strict=True)), rejected, keys


def _explore(
    spec: Spec,
    initial_ctxs: list[dict],
    max_states: int,
    root_numbers: list[int] | None,
    inert_roots: frozenset[int],
    store_edges: bool = True,
    projection: frozenset[Var] | None = None,
) -> Exploration:
    exp = Exploration(store_edges=store_edges)

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
                Code.ACTION_EXCLUDED,
            )

    # Seed the BFS with every admissible initial state; identical roots merge
    # naturally through the state key (research/16: multi-root exploration).
    # Each frontier entry also carries the actions already known REJECTED in it:
    # those its parent rejected whose guard reads the parent's transition left
    # untouched (``_guard_invalidation``); they are skipped, not re-evaluated.
    invariant_plans = {id(inv): InvariantPlan(inv) for inv in spec.invariants}
    queue = _Frontier()
    for pos, ctx in enumerate(initial_ctxs):
        index = root_numbers[pos] if root_numbers is not None else pos + 1
        key0 = (
            state_key(ctx)
            if projection is None
            else _key_in_layout(ctx, *_state_layout(tuple(ctx), projection))
        )
        if key0 in exp.index:
            continue
        idx0 = exp.add_state(key0, -1, -1)
        exp.roots[key0] = index
        # An initial state that already violates an invariant is illegal: keep it
        # as a witness but do not explore from it, exactly as for any successor.
        invalid = _report_invariant_violations(spec, ctx, key0, exp, plans=invariant_plans)
        if invalid or pos in inert_roots:
            exp.invalid_roots.add(idx0)
        else:
            queue.push(idx0, ctx, 0, tuple(ctx))
    codes = [exp.action_code(action.id) for action in spec.actions]
    invalidated = _guard_invalidation(spec)
    rechecks = _invariant_rechecks(spec)
    plans = [build_plan(action, spec.lifecycles) for action in spec.actions]
    numbered = list(enumerate(zip(spec.actions, codes, plans, strict=True)))
    slots_by_layout: dict[int, list[tuple]] = {}
    index_get = exp.index.get
    add_src, add_act, add_dst = exp.edge_src.append, exp.edge_action.append, exp.edge_dst.append
    while queue:
        if len(exp.keys) >= max_states:
            exp.capped = True
            exp.growing = _growing_fields(spec)
            break
        idx, ctx, rejected, keys = queue.pop_state()
        successors: list[tuple[int, dict, int]] = []
        parent_codes = list(_codes(exp.keys[idx]))
        layout_id = parent_codes[0]
        slots_by_action = slots_by_layout.get(layout_id)
        if slots_by_action is None:
            slots_by_action = slots_by_layout[layout_id] = [
                tuple(
                    (slot, entry)
                    for slot, entry in enumerate(_LAYOUTS[layout_id])
                    if entry[0] in plan.changed
                )
                for plan in plans
            ]

        for i, (action, code, plan) in numbered:
            if rejected >> i & 1 or action.id in exp.excluded:
                continue
            result = step(spec, action, ctx, explain=False, plan=plan)
            if result.entered:
                exp.fired.add(action.id)
            if result.outcome is Outcome.REJECTED:
                rejected |= 1 << i
                continue  # a guard disabled the action; its reason is a scenario concern
            if result.outcome is Outcome.DEFECT:
                # step is pure: re-run it with the trace only now that a defect
                # needs one (building the trace for every step was a hot spot)
                for finding in step(spec, action, ctx, trace=exp._trace(idx), plan=plan).findings:
                    exp.report_once(
                        finding.severity, finding.location, finding.message, finding.code
                    )
                continue

            post = result.post_context
            if not action.effect:
                # an accepted effectless action is a self-loop with its post held true
                if store_edges:
                    add_src(idx)
                    add_act(code)
                    add_dst(idx)
                continue
            assert post is not None
            try:
                # Custom copying can change other slots, and Create can add a
                # slot to a hand-built context. Both require full keying.
                k2 = (
                    _successor_key(parent_codes, post, slots_by_action[i])
                    if not result.custom_copy and len(post) == len(ctx)
                    else _key_in_layout(post, *_state_layout(tuple(post), projection))
                    if projection is not None
                    else state_key(post)
                )
            except TypeError as exc:
                exp.report_once(
                    Severity.ERROR,
                    f"action:{action.id}",
                    f"'{action.id}' produces an unhashable state value ({exc}) — "
                    f"the engine supports scalar, enum, str and bool fields only",
                    Code.UNSUPPORTED_VALUE,
                )
                continue
            known = index_get(k2)
            idx2 = exp.add_state(k2, idx, code) if known is None else known
            if store_edges:
                add_src(idx)
                add_act(code)
                add_dst(idx2)
            if known is not None:
                continue
            # the parent is legal: only invariants reading what changed can break
            if _report_invariant_violations(
                spec, post, k2, exp, rechecks[i], plans=invariant_plans
            ):
                continue  # illegal state: reported, not expanded further
            successors.append((idx2, post, i))
        # pushed after the loop, when this state's rejections are all known
        for idx2, post, i in successors:
            # Effects can add a slot to a hand-built context passed to explore().
            queue.push(
                idx2,
                post,
                rejected & ~invalidated[i],
                keys if len(post) == len(keys) else tuple(post),
            )

    return exp


def _guard_reads(action: Action, lock_fields: dict[type, list[str]]) -> set[Var]:
    """Every variable a REJECTED outcome of ``step`` can depend on: the ``pre``
    reads, the presence guards and the terminal lock's lifecycle fields."""
    reads: set[Var] = set()
    for pred in action.pre:
        _pred_vars(pred, reads)
    frozen = set()
    for effect in action.effect:
        if isinstance(effect, (Set, Add, Subtract)):
            frozen.add(_target_key(effect))
        elif isinstance(effect, (Create, Delete)):
            reads.add((effect.target, PRESENT))
            if isinstance(effect, Delete):
                frozen.add(effect.target)
        else:
            raise _Unsliceable(effect)
    for key in frozen:
        if isinstance(key, InstanceRef):
            reads.add((key, PRESENT))
        cls = key.entity_cls if isinstance(key, InstanceRef) else key
        reads.update((key, name) for name in lock_fields.get(cls, ()))
    return reads


def _guard_invalidation(spec: Spec) -> list[int]:
    """Per action (in ``spec.actions`` order): the bitmask of actions whose
    guards may read a variable it writes. An action REJECTED in a state stays
    REJECTED in a successor reached by an action that does not invalidate it —
    every variable its guards read is unchanged. Guards or effects the walker
    does not know are never skipped."""
    lock_fields: dict[type, list[str]] = {}
    for lc in spec.lifecycles:
        if lc.terminal:
            lock_fields.setdefault(lc.entity_cls, []).append(lc.field_name)
    readers: dict[Var, int] = {}
    unknown = 0
    for i, action in enumerate(spec.actions):
        try:
            reads = _guard_reads(action, lock_fields)
        except _Unsliceable:
            unknown |= 1 << i
            continue
        for var in reads:
            readers[var] = readers.get(var, 0) | 1 << i
    everything = (1 << len(spec.actions)) - 1
    masks = []
    for action in spec.actions:
        try:
            writes = _action_writes(action)
        except _Unsliceable:
            masks.append(everything)
            continue
        mask = unknown
        for var in writes:
            mask |= readers.get(var, 0)
        masks.append(mask)
    return masks


def _invariant_rechecks(spec: Spec) -> list[tuple[Invariant, ...]]:
    """Per action (in ``spec.actions`` order): the invariants a successor it
    reaches must re-check. Its parent was legal (every applicable invariant
    held, none failed to evaluate), and an invariant reading no variable the
    action writes has the same applicability and value in the successor.
    Expressions or effects the walker does not know are always re-checked."""
    reads: list[set[Var] | None] = []
    for inv in spec.invariants:
        out: set[Var] = set()
        try:
            _pred_vars(inv.expression, out)
        except _Unsliceable:
            reads.append(None)
            continue
        reads.append(out)
    rechecks = []
    for action in spec.actions:
        try:
            writes = _action_writes(action)
        except _Unsliceable:
            rechecks.append(tuple(spec.invariants))
            continue
        rechecks.append(
            tuple(
                inv
                for inv, read in zip(spec.invariants, reads, strict=True)
                if read is None or not read.isdisjoint(writes)
            )
        )
    return rechecks


def _report_invariant_violations(
    spec: Spec,
    ctx: dict,
    key: StateKey,
    exp: Exploration,
    invariants: Sequence[Invariant] | None = None,
    *,
    plans: dict[int, InvariantPlan],
) -> bool:
    violated = False
    for inv in spec.invariants if invariants is None else invariants:
        plan = plans[id(inv)]
        if not plan.is_applicable(ctx):
            continue  # a referenced entity/Scope slot is absent — not applicable here
        try:
            ok = plan.holds(ctx)
        except Exception as exc:
            # an unevaluable invariant is a model defect, not a pass: mark the
            # state illegal so it is kept as a witness but not expanded, matching
            # how the scenario runner treats the same error
            violated = True
            exp.report_once(
                Severity.ERROR,
                f"invariant:{inv.id}",
                f"evaluation error: {exc} [at: {_trace_str(exp.trace_to(key))}]",
                Code.INVARIANT_EVALUATION_ERROR,
                state=exp.index[key],
            )
            continue
        if not ok:
            violated = True
            exp.finding_states[len(exp.findings)] = {exp.index[key]}
            exp.findings.append(
                Finding(
                    Severity.ERROR,
                    f"invariant:{inv.id}",
                    f"invariant '{inv.label or _describe(inv.expression)}' breaks "
                    f"[after: {_trace_str(exp.trace_to(key))}]",
                    Code.INVARIANT_VIOLATED,
                )
            )
    return violated


# ── Query evaluation ───────────────────────────────────────────────────────────


def resolve_query_initials(
    query: Query, spec: Spec, *, intern: bool = True
) -> tuple[list[dict] | None, str | None]:
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
        built, error = build_initial_relation(spec, effective_initial, intern=intern)
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
    coverage_actions: tuple[Action, ...] | None = None,
    initial_state: tuple[list[dict] | None, str | None] | None = None,
) -> QueryResult:
    """``max_states`` overrides the query's own budget (``check --max-states``).
    With ``analysis`` the query is checked on its slice (research/34 §5).
    ``explorations``, when given, receives the exploration the result was
    decided on (by query id), so a trace replays exactly the check.
    Timing includes root construction, action coverage, exploration and query
    evaluation performed by this call; cached work is not charged again."""
    started = perf_counter()
    result = _run_query(
        query,
        spec,
        cache,
        max_states=max_states,
        analysis=analysis,
        explorations=explorations,
        coverage_actions=coverage_actions,
        initial_state=initial_state,
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
    coverage_actions: tuple[Action, ...] | None = None,
    initial_state: tuple[list[dict] | None, str | None] | None = None,
) -> QueryResult:
    qid = query.id or type(query).__name__
    explorations = {} if explorations is None else explorations
    kind = type(query).__name__

    initials, error = (
        initial_state if initial_state is not None else resolve_query_initials(query, spec)
    )
    if initials is None:
        return QueryResult(
            query_id=qid,
            kind=kind,
            status="FAIL",
            findings=[
                Finding(
                    Severity.ERROR, f"query:{qid}", error or "bad initial state", Code.QUERY_INVALID
                )
            ],
        )

    if initial_state is not None and (
        query.initial is not None
        or (not (query.given or query.given_any) and spec.initial is not None)
    ):
        # The storage plan built this relation without interning its roots.
        for ctx in initials:
            state_key(ctx)

    budget = query_budget(query, spec.max_states, max_states)
    if not isinstance(query, (Reachable, Unreachable, AlwaysHolds, NoDeadEnd, DeadActions)):
        return QueryResult(
            query_id=qid,
            kind=kind,
            status="FAIL",
            findings=[
                Finding(
                    Severity.ERROR, f"query:{qid}", f"unknown query type {kind}", Code.QUERY_INVALID
                )
            ],
        )
    if analysis is not None:
        # the full exploration of these roots would surface every action's
        # defects; the per-action slices do the same and decide DeadActions
        # invariants were proven from the canonical roots only (SliceAnalysis)
        canonical = not (query.given or query.given_any or query.initial is not None)
        dead_actions = isinstance(query, DeadActions)
        firing_proofs: list[dict] = []
        per_action = cover_actions(
            analysis,
            initials,
            budget,
            cache,
            canonical=canonical,
            actions=None if dead_actions else coverage_actions,
            firing_proofs=firing_proofs if dead_actions else None,
        )
        if dead_actions:
            result = _eval_dead_actions_sliced(qid, spec, per_action)
            if firing_proofs:
                from analint.validator.derived_proof import root_source

                result.model = {
                    "relation": (
                        "under-approx: replayed"
                        if result.status == QueryStatus.PASS
                        else "exact"
                        if result.status == QueryStatus.FAIL
                        else None
                    ),
                    "system_id": spec.id,
                    "view_id": None,
                    "proof_rule": "projection",
                    "root_source": root_source(query),
                    "root_numbers": list(range(1, len(initials) + 1)),
                    "attempts": firing_proofs,
                }
            return result
        if isinstance(query, NoDeadEnd):  # a closed lock creates dead ends
            piece = analysis.predicate_slice(query.goal, locks=True, canonical=canonical)
            candidate = analysis.recoverability_slice(
                query.goal, piece, initials, canonical=canonical
            )
            if candidate is not None:
                free, flag_count = candidate
                exp, used = explore_slice(analysis, free, initials, budget, cache, clean_only=True)
                # Restoring all flags maps every full state into this graph.
                # Preserve the full slice's budget verdict even when the
                # smaller graph completed within the budget.
                if (
                    not exp.capped
                    and not exp.findings
                    and not exp.excluded
                    and (len(exp.states) << flag_count) < budget
                ):
                    result = _evaluate(query, qid, exp, spec)
                    if result.status == QueryStatus.PASS:
                        explorations[qid] = exp
                        result.slice = {**used.summary(), "restorable_flags": flag_count}
                        return result
                # BFS order, invalid-state attribution and diagnostic traces
                # belong to the full exploration whenever a proof fails.
        else:
            piece = analysis.predicate_slice(query.predicate, canonical=canonical)
        from analint.validator.derived_proof import attempt, reach_witness

        coverage_complete = not any(
            per_action[id(action)].capped for action in piece.actions if id(action) in per_action
        )
        reach_probe = None
        if isinstance(query, Reachable) and coverage_complete:
            reach_probe = reach_witness(query, analysis, piece, initials, budget)
            if reach_probe is not None and reach_probe.witness is not None:
                result, explorations[qid] = reach_probe.witness
                _retain_exact_statistics(result, analysis, piece, initials, budget)
                return result

        probe = None
        if isinstance(query, Unreachable):
            probe = attempt(query, analysis, piece, initials, budget)
            if (
                probe is not None
                and probe.proved
                and (coverage_complete or coverage_actions is not None)
            ):
                probe.result.model = probe.report()
                explorations[qid] = probe.graph
                assert isinstance(probe.result, QueryResult)
                _retain_exact_statistics(probe.result, analysis, piece, initials, budget)
                return probe.result
        exp, used = explore_slice(analysis, piece, initials, budget, cache)
        explorations[qid] = exp
        result = _evaluate(query, qid, exp, spec)
        result.slice = used.summary()
        if reach_probe is not None:
            reach_probe.record_exact(result, exp, budget)
        if probe is not None:
            if result.status == QueryStatus.INCONCLUSIVE and probe.replayed is not None:
                replay, explorations[qid] = probe.replayed
                assert isinstance(replay, QueryResult)
                replay.model = probe.report(result, budget, exact_graph=exp, replayed=True)
                return replay
            result.model = probe.report(result, budget, exact_graph=exp)
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


def _retain_exact_statistics(
    result: InvariantResult | QueryResult,
    analysis: SliceAnalysis,
    piece: Slice,
    initials: list[dict],
    budget: int,
) -> None:
    """Retain legacy statistics when exact coverage already built this graph."""
    for used, exp in analysis.explored.get((analysis.roots_key(initials), budget), ()):
        if used.key == piece.key and not exp.capped and not exp.excluded:
            result.states_explored = exp.state_count
            result.slice = used.summary()
            return


def explore_slice(
    analysis: SliceAnalysis,
    piece: Slice,
    initials: list[dict],
    max_states: int,
    cache: dict,
    *,
    reuse_superset: bool = False,
    clean_only: bool = False,
) -> tuple[Exploration, Slice]:
    """Explore one slice (research/34 §5); returns the exploration and the
    slice it actually covers. A complete exploration of a closed superset is
    exact for every slice inside it; ``reuse_superset`` answers from it instead
    of exploring (used by the per-action coverage — a property reports its own,
    smallest slice). A speculative proof records only complete, clean graphs
    so its findings cannot leak into the report on fallback."""
    if piece.vars is None:
        return explore_cached(analysis.spec, initials, max_states, cache), piece
    explored = analysis.explored.setdefault((analysis.roots_key(initials), max_states), [])
    existing = _existing_slice(analysis, piece, explored, reuse_superset=reuse_superset)
    if existing is not None:
        return existing
    roots, numbers, inert = analysis.project_roots(piece, initials)
    store_edges = not isinstance(cache, ExplorationStorage) or cache.stores_edges(
        initials, max_states, piece
    )
    exp = explore(
        analysis.sliced_spec(piece),
        roots,
        max_states,
        root_numbers=numbers,
        inert_roots=inert,
        store_edges=store_edges,
    )
    if not clean_only or (not exp.capped and not exp.findings and not exp.excluded):
        explored.append((piece, exp))
        if isinstance(cache, ExplorationStorage):
            cache.track(initials, max_states, exp)
    return exp, piece


def _existing_slice(
    analysis: SliceAnalysis,
    piece: Slice,
    explored: list[tuple[Slice, Exploration]],
    *,
    reuse_superset: bool,
) -> tuple[Exploration, Slice] | None:
    for used, exp in explored:
        if used.key == piece.key or (
            reuse_superset
            and not exp.capped
            and piece.vars is not None
            and used.vars is not None
            and piece.vars <= used.vars
            # more variables need not mean more actions: an effectless action,
            # or a writer that only switches a flag off, joins only its own slice
            and {id(a) for a in piece.actions} <= {id(a) for a in used.actions}
            and analysis.is_exact(used)
        ):
            return exp, used
    return None


def cover_actions(
    analysis: SliceAnalysis,
    initials: list[dict],
    max_states: int,
    cache: dict,
    *,
    canonical: bool,
    actions: tuple[Action, ...] | None = None,
    firing_proofs: list[dict] | None = None,
) -> dict[int, Exploration]:
    """Explore the requested actions in their own slices to assess defects and
    fireability. With no subset, this is the sliced counterpart of one full
    exploration. Results are keyed by id(action)."""
    from analint.validator.derived_proof import cover_defects, firing_witness

    actions = tuple(analysis.spec.actions) if actions is None else actions
    root_key = (analysis.roots_key(initials), max_states, canonical)
    require_firing = firing_proofs is not None
    key = (*root_key, tuple(map(id, actions)), require_firing)
    if key not in analysis.covered:
        # largest slices first, so the nested ones reuse their explorations
        pieces = []
        for action in actions:
            narrow = analysis.local_enabler_slice(action, initials, canonical=canonical)
            piece = narrow or analysis.action_slice(action, canonical=canonical)
            pieces.append((action, piece, narrow is not None))
        pieces.sort(key=lambda item: -len(item[1].vars or ()))
        covered = {}
        witnesses = []
        proofs = analysis.projected_coverage.setdefault(root_key, {})

        def prove(action: Action) -> tuple | None:
            identity = id(action)
            if identity not in proofs:
                proofs[identity] = cover_defects(
                    action,
                    analysis,
                    analysis.action_slice(action, canonical=canonical),
                    initials,
                    max_states,
                    canonical=canonical,
                )
            return proofs[identity]

        requested = {id(action) for action in actions}
        for action, piece, narrow in pieces:
            identity = id(action)
            if require_firing and piece.vars is not None:
                existing = _existing_slice(
                    analysis, piece, analysis.explored.get(root_key[:2], []), reuse_superset=True
                )
                if (
                    existing is not None
                    and not existing[0].capped
                    and (not narrow or action.id in existing[0].fired)
                ):
                    covered[identity] = existing[0]
                    continue
            if not narrow:
                proof = prove(action)
                if proof is not None and all(
                    id(dep) in requested or prove(dep) is not None for dep in piece.actions
                ):
                    if not require_firing:
                        covered[identity] = proof[1]
                        continue
                    witness = firing_witness(action, analysis, piece, initials, proof)
                    if witness is not None:
                        witnesses.append(witness)
                        covered[identity] = proof[1]
                        continue
            exp = explore_slice(analysis, piece, initials, max_states, cache, reuse_superset=True)[
                0
            ]
            if narrow and (exp.capped or action.id not in exp.fired):
                # A narrow graph can prove a real firing, never absence of one.
                # Completeness also gates the local enabler's defect argument.
                exp = explore_slice(
                    analysis,
                    analysis.action_slice(action, canonical=canonical),
                    initials,
                    max_states,
                    cache,
                    reuse_superset=True,
                )[0]
            covered[id(action)] = exp
        analysis.covered[key] = covered, witnesses
    covered, witnesses = analysis.covered[key]
    if firing_proofs is not None:
        firing_proofs.extend(witnesses)
    return covered


def explore_cached(spec: Spec, initials: list[dict], max_states: int, cache: dict) -> Exploration:
    """One exploration per (root set, budget) within a validate() run: the
    canonical invariant check and default-source queries share a state space."""
    root_keys = tuple(dict.fromkeys(state_key(ctx) for ctx in initials))
    cache_key = (root_keys, max_states)
    if cache_key not in cache:
        store_edges = not isinstance(cache, ExplorationStorage) or cache.stores_edges(
            initials, max_states, None
        )
        exp = explore(spec, initials, max_states, store_edges=store_edges)
        cache[cache_key] = exp
        if isinstance(cache, ExplorationStorage):
            cache.track(initials, max_states, exp)
    return cache[cache_key]


class ExplorationStorage(dict):
    """In-run whole-model memo and storage plan for validation's graph consumers."""

    def __init__(self, analysis: SliceAnalysis | None = None) -> None:
        super().__init__()
        self.analysis = analysis
        self.remaining: Counter = Counter()
        self.edge_slices: dict[tuple, set] = {}
        self.groups: dict[tuple, list[Exploration]] = {}
        self._root_sets: dict[int, tuple[list[dict], tuple]] = {}

    def group(self, initials: list[dict], budget: int) -> tuple:
        cached = self._root_sets.get(id(initials))
        if cached is None:
            roots = tuple(dict.fromkeys(map(_root_signature, initials)))
            cached = self._root_sets[id(initials)] = (initials, roots)
        return cached[1], budget

    def register(self, initials: list[dict] | None, budget: int) -> tuple | None:
        if initials is None:
            return None
        group = self.group(initials, budget)
        self.remaining[group] += 1
        return group

    def plan_query(self, query: Query, initials: list[dict] | None, budget: int) -> tuple | None:
        group = self.register(initials, budget)
        if group is None or initials is None:
            return group
        locks = isinstance(query, NoDeadEnd)
        if not locks and not (isinstance(query, Reachable) and len(group[0]) > 1):
            return group
        wanted = self.edge_slices.setdefault(group, set())
        analysis = self.analysis
        if analysis is None:
            wanted.add(None)
            return group

        goal = query.goal if isinstance(query, NoDeadEnd) else query.predicate
        canonical = not (query.given or query.given_any or query.initial is not None)
        # Trust can select the free or constrained cone. Both have fixed
        # identities, so plan them before building any shared graphs.
        for unconstrained in (False, True) if canonical else (False,):
            piece = analysis.predicate_slice(
                goal, locks=locks, canonical=False, unconstrained=unconstrained
            )
            wanted.add(None if piece.vars is None else piece.key)
            if locks:
                lock_free = analysis.predicate_slice(
                    goal, canonical=False, unconstrained=unconstrained
                )
                candidate = analysis.recoverability_slice(
                    goal, piece, initials, canonical=canonical, free=lock_free
                )
                if candidate is not None:
                    wanted.add(candidate[0].key)
        return group

    def stores_edges(self, initials: list[dict], budget: int, piece: Slice | None) -> bool:
        group = self.group(initials, budget)
        return (None if piece is None else piece.key) in self.edge_slices.get(group, ())

    def track(self, initials: list[dict], budget: int, exp: Exploration) -> None:
        group = self.group(initials, budget)
        self.groups.setdefault(group, []).append(exp)

    def finish(self, group: tuple | None, decided: dict[str, Exploration] | None) -> None:
        if group is None:
            return
        self.remaining[group] -= 1
        if self.remaining[group]:
            return
        pinned = {id(exp) for exp in decided.values()} if decided is not None else set()
        for exp in self.groups.pop(group, ()):
            if id(exp) not in pinned:
                exp.release_graph()


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
    invariants: list[Invariant] | None = None,
    max_states: int = 10_000,
    cache: dict | None = None,
    analysis: SliceAnalysis | None = None,
    explorations: dict[str, Exploration] | None = None,
    all_actions: bool = True,
) -> tuple[list[InvariantResult], Exploration | None]:
    """Verify every world invariant over the reachable states of the canonical
    model (or only ``invariants`` when supplied, without changing constraints).
    ``initials`` is the pre-built canonical state set (see
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
    targets = spec.invariants if invariants is None else invariants
    explorations = {} if explorations is None else explorations
    if not targets:
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
                        Code.INVARIANT_NOT_CHECKED,
                    )
                ],
            )
            for inv in targets
        ]
        return results, None

    cache = {} if cache is None else cache
    if analysis is not None:
        # Phase 1: each invariant on its unconstrained slice. That model prunes
        # less than the whole one, so a PASS there is final — and makes the
        # invariant trusted: it never prunes, other slices need not include it.
        from analint.validator.derived_proof import attempt

        pending = []
        proved = {}
        probes = {}
        for inv in targets:
            started = perf_counter()
            piece = analysis.invariant_slice(inv, unconstrained=True)
            probe = attempt(inv, analysis, piece, initials, max_states)
            if probe is not None:
                probes[id(inv)] = probe
                if probe.proved:
                    result = probe.result
                    assert isinstance(result, InvariantResult)
                    result.model = probe.report()
                    result.elapsed_ms = (perf_counter() - started) * 1000
                    proved[id(inv)] = result
                    explorations[inv.id] = probe.graph
                    continue
            exp, used = explore_slice(
                analysis,
                piece,
                initials,
                max_states,
                cache,
            )
            pending.append((inv, exp, used, (perf_counter() - started) * 1000))
            explorations[inv.id] = exp
        # invariants sharing an exploration are checked in one pass over it
        verdicts = _verify_grouped([(inv, exp) for inv, exp, _, _ in pending])
        checked = []
        for (inv, exp, used, explore_ms), result in zip(pending, verdicts, strict=True):
            result.elapsed_ms = (result.elapsed_ms or 0.0) + explore_ms
            if result.status == QueryStatus.PASS:
                analysis.trusted.add(id(inv))
            checked.append((inv, result, used, exp))
        analysis.trusted.update(proved)
        # Phase 2: a FAIL is true of the whole model only on an exact slice.
        results_by_target = dict(proved)
        for inv, result, used, exp in checked:
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
            probe = probes.get(id(inv))
            if probe is not None:
                if result.status == QueryStatus.INCONCLUSIVE and probe.replayed is not None:
                    replay, explorations[inv.id] = probe.replayed
                    assert isinstance(replay, InvariantResult)
                    replay.model = probe.report(result, max_states, exact_graph=exp, replayed=True)
                    replay.elapsed_ms = result.elapsed_ms
                    result = replay
                else:
                    result.model = probe.report(result, max_states, exact_graph=exp)
            results_by_target[id(inv)] = result
        # defects parity with the full canonical exploration (see cover_actions)
        if all_actions:
            coverage = cover_actions(analysis, initials, max_states, cache, canonical=True)
            for inv in targets:
                if id(inv) not in proved:
                    continue
                piece = analysis.invariant_slice(inv, unconstrained=True)
                if not any(coverage[id(action)].capped for action in piece.actions):
                    continue
                # A safety proof may erase a real diagnostic. Preserve the
                # original check when relevant defect coverage reached its cap.
                started = perf_counter()
                exp, used = explore_slice(analysis, piece, initials, max_states, cache)
                result = _verify_one_invariant(inv, exp)
                result.slice = used.summary()
                result.model = probes[id(inv)].report(result, max_states, exact_graph=exp)
                result.elapsed_ms = (proved[id(inv)].elapsed_ms or 0.0) + (
                    perf_counter() - started
                ) * 1000
                results_by_target[id(inv)] = result
                explorations[inv.id] = exp
        return [results_by_target[id(inv)] for inv in targets], None
    # Charge the shared exploration to the first invariant that requests it.
    started = perf_counter()
    exp = explore_cached(spec, initials, max_states, cache)
    explore_ms = (perf_counter() - started) * 1000
    results = _verify_invariants(targets, exp)
    results[0].elapsed_ms = (results[0].elapsed_ms or 0.0) + explore_ms
    for inv in targets:
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
    plans = [InvariantPlan(inv) for inv in invs]
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
            outcome = _check_invariant_at(inv, exp, key, ctx, plans[i])
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
    inv: Invariant, exp: Exploration, key: StateKey, ctx: dict, plan: InvariantPlan
) -> InvariantResult | bool | None:
    """None — not applicable here; True — holds; a FAIL ``InvariantResult``
    otherwise."""
    if not plan.is_applicable(ctx):
        return None  # presence-aware: a referenced entity/slot is absent here
    try:
        ok = plan.holds(ctx)
    except Exception as exc:
        return _invariant_failure(
            inv, exp, key, f"evaluation error: {exc}", Code.INVARIANT_EVALUATION_ERROR
        )
    if ok:
        return True
    label = inv.label or _describe(inv.expression)
    return _invariant_failure(
        inv,
        exp,
        key,
        f"invariant '{label}' is violated: {exp.origin(key)}{_trace_str(exp.trace_to(key))}",
        Code.INVARIANT_VIOLATED,
    )


def _invariant_failure(
    inv: Invariant, exp: Exploration, key: StateKey, message: str, code: Code
) -> InvariantResult:
    return InvariantResult(
        invariant_id=inv.id,
        label=inv.label or _describe(inv.expression),
        status=QueryStatus.FAIL,
        states_explored=len(exp.states),
        trace=exp.trace_to(key),
        witness_key=key,
        findings=[Finding(Severity.ERROR, f"invariant:{inv.id}", message, code)],
    )


def _invariant_outcome(inv: Invariant, exp: Exploration, evaluated: bool) -> InvariantResult:
    """The verdict of an invariant that no explored state violated."""
    label = inv.label or _describe(inv.expression)
    loc = f"invariant:{inv.id}"
    # "never evaluable" is a claim about every reachable state: a capped or
    # partial exploration may simply not have reached an applicable one
    if not evaluated and not exp.capped and not exp.excluded:
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
                    Code.INVARIANT_NOT_CHECKED,
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
                    f"inconclusive: exploration hit max_states before the state space "
                    f"was exhausted — {_cap_hint(exp, tlc=True)}",
                    Code.BUDGET_EXHAUSTED,
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
                    Code.EXCLUDED_ACTIONS,
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
    matches: array = dc_field(default_factory=lambda: array("i"))
    applicable: int = 0
    errors: list = dc_field(default_factory=list)


def _query_contexts(exp: Exploration, predicate: Predicate, required: frozenset) -> Iterator[dict]:
    """Reuse decoded contexts for repeat combinations of the slots a query reads."""
    keys = exp.order
    reads: set[Var] = set()
    try:
        _pred_vars(predicate, reads)
    except _Unsliceable:
        yield from map(decode_state, keys)
        return

    if keys:
        layout_id = _codes(keys[0])[0]
        layout = _LAYOUTS[layout_id]
        owners = required | {owner for owner, _ in reads}
        slots = [i for i, (owner, _, _) in enumerate(layout, start=1) if owner in owners]
        if layout_id < _ESCAPE and slots and slots[-1] - slots[0] + 1 < len(layout):
            # Fixed-width keys put all relevant slot codes in one byte span.
            # A different layout or any escaped code requires ordinary decoding.
            prefix = keys[0][:2]
            width = 2 * (len(layout) + 1)
            span = slice(2 * slots[0], 2 * (slots[-1] + 1))
            cached = exp._query_context_cache
            if cached is None or cached[:2] != (layout_id, owners):
                cached = exp._query_context_cache = (layout_id, owners, {})
            cache = cached[2]
            for key in keys:
                if len(key) != width or not key.startswith(prefix):
                    yield decode_state(key)
                    continue
                signature = key[span]
                ctx = cache.get(signature)
                if ctx is None:
                    full = decode_state(key)
                    ctx = {owner: full[owner] for owner in owners if owner in full}
                    if len(cache) < 4096:
                        cache[signature] = ctx
                yield ctx
            return
    yield from map(decode_state, keys)


def _scan_states(exp: Exploration, predicate: Predicate, *, collect_matches: bool = False) -> _Scan:
    scan = _Scan()
    required = frozenset(field_context_key(ref) for ref in _collect_field_refs(predicate))
    check = None
    contexts = _query_contexts(exp, predicate, required)
    for idx, (key, ctx) in enumerate(zip(exp.order, contexts, strict=True)):
        if not required <= ctx.keys():
            continue
        scan.applicable += 1
        try:
            if check is None:
                check = compile_predicate(predicate)
            if check(ctx):
                if collect_matches:
                    scan.matches.append(idx)
                if scan.first_match is None:
                    scan.first_match = key
        except Exception as exc:
            message = f"evaluation error: {exc} [at: {_trace_str(exp.trace_to(key))}]"
            if message not in scan.errors:
                scan.errors.append(message)
    return scan


def _co_reachable(exp: Exploration, goals: Iterable[int]) -> bytearray:
    """Return a visitation flag per state with a path to a goal."""
    exp._require_edges()
    # Each target owns a chain of incoming edge indices. Reuse the forward
    # graph's sources so the reverse index needs only one integer per edge.
    incoming = array("i", [-1]) * len(exp.keys)
    previous = array("i", [-1]) * len(exp.edge_dst)
    for edge, dst in enumerate(exp.edge_dst):
        previous[edge] = incoming[dst]
        incoming[dst] = edge

    reached = bytearray(len(exp.keys))
    stack = array("i", goals)
    for goal in stack:
        reached[goal] = 1
    sources = exp.edge_src
    while stack:
        edge = incoming[stack.pop()]
        while edge >= 0:
            src = sources[edge]
            if not reached[src]:
                reached[src] = 1
                stack.append(src)
            edge = previous[edge]
    return reached


def _model_error_result(qid: str, kind: str, exp: Exploration, problems: list[str]) -> QueryResult:
    return QueryResult(
        query_id=qid,
        kind=kind,
        status="FAIL",
        states_explored=len(exp.states),
        findings=[
            Finding(Severity.ERROR, f"query:{qid}", p, Code.QUERY_EVALUATION_ERROR)
            for p in problems
        ],
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
                Code.QUERY_VACUOUS,
            )
        ],
    )


def _invalid_root_finding(qid: str, number: int) -> Finding:
    return Finding(
        Severity.ERROR,
        f"query:{qid}",
        f"init #{number} is invalid under model invariants; "
        "reachability was not assessed from this root (not expanded)",
        Code.QUERY_INVALID_ROOT,
    )


def _eval_reachable(
    query: Reachable | Unreachable,
    qid: str,
    exp: Exploration,
    expect_reachable: bool,
) -> QueryResult:
    kind = type(query).__name__
    text = query.label or _describe(query.predicate)
    multi_root = expect_reachable and len(exp.roots) > 1
    scan = _scan_states(exp, query.predicate, collect_matches=multi_root)
    if scan.errors:
        return _model_error_result(qid, kind, exp, scan.errors)
    if scan.applicable == 0:
        return _never_applicable_result(qid, kind, exp, text)
    found = scan.first_match
    if expect_reachable and found is not None and exp.index[found] in exp.invalid_roots:
        found = None  # an inert root cannot certify a positive reachability witness

    if multi_root:
        reached = _co_reachable(exp, scan.matches)
        missing_roots = [
            root
            for root in exp.roots
            if not reached[exp.index[root]] or exp.index[root] in exp.invalid_roots
        ]
        # Prefer real missing-path evidence over a root already known invalid.
        missing = next(
            (root for root in missing_roots if exp.index[root] not in exp.invalid_roots),
            missing_roots[0] if missing_roots else None,
        )
        if missing is not None:
            if exp.capped:
                return _inconclusive(qid, kind, exp)
            if exp.excluded:
                return _excluded_actions_result(qid, kind, exp)
            return QueryResult(
                query_id=qid,
                kind=kind,
                status="FAIL",
                states_explored=len(exp.states),
                trace=[],
                witness_key=missing,
                findings=[
                    Finding(
                        Severity.ERROR,
                        f"query:{qid}",
                        f"'{text}' is not reachable from init #{exp.roots[missing]} "
                        f"(explored all {len(exp.states)} states)",
                        Code.NOT_REACHABLE,
                    )
                    if exp.index[missing] not in exp.invalid_roots
                    else _invalid_root_finding(qid, exp.roots[missing]),
                    *_origin_findings(exp, missing, qid),
                ],
            )

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
                        Code.WITNESS,
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
                    Code.REACHED_FORBIDDEN,
                ),
                *_origin_findings(exp, found, qid),
            ],
        )

    if exp.capped:
        return _inconclusive(qid, kind, exp)
    if exp.excluded:
        return _excluded_actions_result(qid, kind, exp)
    if expect_reachable:
        invalid = next((root for root in exp.roots if exp.index[root] in exp.invalid_roots), None)
        if invalid is not None:
            return QueryResult(
                query_id=qid,
                kind=kind,
                status="FAIL",
                states_explored=len(exp.states),
                trace=[],
                witness_key=invalid,
                findings=[
                    _invalid_root_finding(qid, exp.roots[invalid]),
                    *_origin_findings(exp, invalid, qid),
                ],
            )
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
                    Code.NOT_REACHABLE,
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
                        Code.PROPERTY_VIOLATED,
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
    if exp.excluded:
        return _excluded_actions_result(qid, "AlwaysHolds", exp)
    return QueryResult(
        query_id=qid, kind="AlwaysHolds", status="PASS", states_explored=len(exp.states)
    )


def _dead_end_finding(
    qid: str, goal: str, exp: Exploration, key: StateKey, trace: list[str]
) -> Finding:
    """Explain the chosen witness only from its invariant-to-state provenance."""
    idx = exp.index[key]
    reasons: dict[Code, list[str]] = {}
    for finding_idx, states in exp.finding_states.items():
        finding = exp.findings[finding_idx]
        if (
            idx in states
            and finding.severity is Severity.ERROR
            and finding.code
            in (
                Code.INVARIANT_VIOLATED,
                Code.INVARIANT_EVALUATION_ERROR,
            )
        ):
            names = reasons.setdefault(finding.code, [])
            name = finding.location.removeprefix("invariant:")
            if name not in names:
                names.append(name)
    prefix = f"dead end: after {exp.origin(key)}{_trace_str(trace)}"
    if reasons:
        details = "; ".join(
            f"{label}: {', '.join(repr(name) for name in reasons[code])}"
            for code, label in (
                (Code.INVARIANT_VIOLATED, "violated"),
                (Code.INVARIANT_EVALUATION_ERROR, "evaluation failed"),
            )
            if code in reasons
        )
        return Finding(
            Severity.ERROR,
            f"query:{qid}",
            f"{prefix} reaches a state invalid under model invariants ({details}); "
            f"the state was not expanded, so recovery to goal '{goal}' was not assessed",
            Code.QUERY_INVALID_STATE,
        )
    return Finding(
        Severity.ERROR,
        f"query:{qid}",
        f"{prefix} the goal '{goal}' can no longer be reached",
        Code.DEAD_END,
    )


def _eval_no_dead_end(query: NoDeadEnd, qid: str, exp: Exploration) -> QueryResult:
    text = query.label or _describe(query.goal)
    if exp.capped:
        return _inconclusive(qid, "NoDeadEnd", exp)

    scan = _scan_states(exp, query.goal, collect_matches=True)
    if scan.errors:
        return _model_error_result(qid, "NoDeadEnd", exp, scan.errors)
    if scan.applicable == 0:
        return _never_applicable_result(qid, "NoDeadEnd", exp, text)
    if exp.excluded:
        # Missing transitions can both hide new dead ends and enable recovery.
        return _excluded_actions_result(qid, "NoDeadEnd", exp)
    if not scan.matches:
        return QueryResult(
            query_id=qid,
            kind="NoDeadEnd",
            status="FAIL",
            states_explored=len(exp.states),
            findings=[
                Finding(
                    Severity.ERROR,
                    f"query:{qid}",
                    f"goal '{text}' is not reachable at all",
                    Code.GOAL_UNREACHABLE,
                )
            ],
        )

    co_reachable = _co_reachable(exp, scan.matches)

    for idx, key in enumerate(exp.order):  # BFS order → shortest trace to the first dead end
        if not co_reachable[idx]:
            trace = exp.trace_to(key)
            return QueryResult(
                query_id=qid,
                kind="NoDeadEnd",
                status="FAIL",
                states_explored=len(exp.states),
                trace=trace,
                witness_key=key,
                findings=[
                    _dead_end_finding(qid, text, exp, key, trace),
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
            Code.NOT_ASSESSED,
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
                Code.DEAD_ACTIONS,
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
                Code.DEAD_ACTIONS,
            )
        )
    if undecided:
        findings.append(
            Finding(
                Severity.WARNING,
                f"query:{qid}",
                f"not decided — their slices exceeded max_states: {', '.join(sorted(undecided))}",
                Code.UNDECIDED,
            )
        )
    findings.extend(
        Finding(
            Severity.INFO,
            f"query:{qid}",
            f"not assessed (excluded from exploration): {aid} — {reason}",
            Code.NOT_ASSESSED,
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


_ARITHMETIC = (_AddExpr, _SubExpr, _MulExpr, _FloorDivExpr, _Sum)


def _growing_fields(spec: Spec) -> list[str]:
    """Numeric fields that some action changes arithmetically with no Field
    bound in that direction — the usual reason a state space never closes."""
    found: set[str] = set()
    for action in spec.actions:
        for effect in action.effect:
            writes: list[tuple[Any, Any, set[str]]] = []
            if isinstance(effect, (Add, Subtract)):
                amount, sign = effect.amount, 1 if isinstance(effect, Add) else -1
                if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                    dirs = {"up"} if sign * amount > 0 else {"down"} if sign * amount < 0 else set()
                else:
                    dirs = {"up", "down"}
                writes.append((*_field_owner(effect.field), dirs))
            elif isinstance(effect, Set) and isinstance(effect.value, _ARITHMETIC):
                writes.append((*_field_owner(effect.field), {"up", "down"}))
            elif isinstance(effect, Create) and isinstance(effect.target, InstanceRef):
                writes += [
                    (effect.target.entity_cls, name, {"up", "down"})
                    for name, value in effect.fields.items()
                    if isinstance(value, _ARITHMETIC)
                ]
            for cls, name, dirs in writes:
                fspec = all_fields(cls)[name].spec
                if fspec is not None and fspec.values is not None:
                    continue
                upper = fspec is not None and (fspec.le is not None or fspec.lt is not None)
                lower = fspec is not None and (fspec.ge is not None or fspec.gt is not None)
                if ("up" in dirs and not upper) or ("down" in dirs and not lower):
                    found.add(f"{cls.__name__}.{name}")
    return sorted(found)


def _field_owner(ref: Any) -> tuple[type, str]:
    if isinstance(ref, InstanceField):
        return ref.instance.entity_cls, ref.field_name
    return ref.entity_cls, ref.field_name


def _cap_hint(exp: Exploration, *, tlc: bool) -> str:
    if exp.growing:
        return (
            f"these numeric fields change with no Field bound in that direction: "
            f"{', '.join(exp.growing)} — bound them with Field(ge=..., le=...)"
        )
    return "raise max_states" + (", or decide it with --tlc" if tlc else "")


def _inconclusive(qid: str, kind: str, exp: Exploration) -> QueryResult:
    tlc = kind in {"Reachable", "Unreachable", "AlwaysHolds"}
    return QueryResult(
        query_id=qid,
        kind=kind,
        status="INCONCLUSIVE",
        states_explored=len(exp.states),
        findings=[
            Finding(
                Severity.WARNING,
                f"query:{qid}",
                f"state space exceeded max_states={len(exp.states)} — {_cap_hint(exp, tlc=tlc)}",
                Code.BUDGET_EXHAUSTED,
            )
        ],
    )


def _excluded_actions_result(qid: str, kind: str, exp: Exploration) -> QueryResult:
    return QueryResult(
        query_id=qid,
        kind=kind,
        status="INCONCLUSIVE",
        states_explored=len(exp.states),
        findings=[
            Finding(
                Severity.WARNING,
                f"query:{qid}",
                "inconclusive: actions ["
                + ", ".join(sorted(exp.excluded))
                + "] were excluded from exploration, so the transition relation is incomplete",
                Code.EXCLUDED_ACTIONS,
            )
        ],
    )


def _origin_findings(exp: Exploration, key: StateKey, qid: str) -> list[Finding]:
    """Describe the initial configuration a trace starts from (multi-root only)."""
    if len(exp.roots) <= 1 and not exp.multiple_roots:
        return []
    root = exp.root_of(key)
    rendered = ", ".join(f"{k}={v}" for k, v in render_state(exp.states[root]).items())
    return [
        Finding(
            Severity.INFO,
            f"query:{qid}",
            f"init #{exp.roots[root]}: {rendered}",
            Code.INITIAL_STATE,
        )
    ]


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
