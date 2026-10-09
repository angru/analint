"""Property slicing (cone of influence) — research/34 §5.

A *variable* is a ``(context key, field)`` pair, or ``(key, "@present")`` for a
Scope slot's presence. The slice of a property is the least closed set of
variables containing what the property reads:

- an action that writes a slice variable joins the slice, and everything it
  reads or writes (guards, effect right-hand sides, post, emitted payloads,
  presence guards, the terminal lock of what it touches) joins the variables;
- an invariant that mentions a slice variable joins, with all its variables.

Exploring only the slice's actions and invariants is exact for the property:

- *slice → full*: a slice state IS a full state (variables outside the slice
  stay in the context at their root values), so every slice trace replays in
  the full model unchanged;
- *full → slice*: an action outside the slice never writes a slice variable,
  and every action inside reads only slice variables, so projected onto the
  slice a full path is a slice path with stutters.

Roots are the full canonical/query roots, deduplicated by their projection
(otherwise the frozen variables would multiply the space); a root that breaks
an invariant outside the slice stays a state but is not expanded, exactly as
the full exploration keeps but does not expand it.

Known, deliberate divergence: a full state that breaks an invariant *outside*
the slice is not expanded in the full model, so a full ``NoDeadEnd`` counts it
as a dead end; the slice does not see it. That violation fails the run on its
own (in its invariant's slice), so the run verdict is unchanged.

Unknown AST nodes never shrink a slice: the property falls back to the whole
model (research/14 §7 — an unsupported node is never silently ignored).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Create, Delete, Set, Subtract
from analint.models.entity import FieldDescriptor, all_fields
from analint.models.expr import _AddExpr, _MulExpr, _SubExpr
from analint.models.invariant import Invariant
from analint.models.predicate import (
    Predicate,
    _And,
    _BinaryComparison,
    _Implies,
    _In,
    _IsNotNull,
    _IsNull,
    _Not,
    _Or,
)
from analint.models.quantifier import (
    Bound,
    BoundField,
    _Count,
    _Exists,
    _ForAll,
    _Max,
    _Min,
    _Present,
    _Sum,
    bind_operand,
    bind_predicate,
)
from analint.models.root import Spec
from analint.models.scope import InstanceField, InstanceRef, context_key_label, is_present
from analint.validator.rule_checker import evaluate
from analint.validator.state_checks import invariant_is_applicable

PRESENT = "@present"
Var = tuple[Any, str]


class _Unsliceable(Exception):
    """An AST node the walker does not know: slicing must not guess."""


# ── variable extraction ──────────────────────────────────────────────────────


def _slots(variable: Bound) -> list[InstanceRef]:
    return list(variable.scope)


def _pred_vars(pred: Any, out: set[Var]) -> None:
    if isinstance(pred, (_And, _Or)):
        for expr in pred.exprs:
            _pred_vars(expr, out)
    elif isinstance(pred, _Not):
        _pred_vars(pred.expr, out)
    elif isinstance(pred, _Implies):
        _pred_vars(pred.left, out)
        _pred_vars(pred.right, out)
    elif isinstance(pred, (_ForAll, _Exists)):
        # a quantifier ranges over present slots: it reads every slot's presence
        for ref in _slots(pred.variable):
            out.add((ref, PRESENT))
            _pred_vars(bind_predicate(pred.predicate, pred.variable, ref), out)
    elif isinstance(pred, _BinaryComparison):
        _operand_vars(pred.left, out)
        _operand_vars(pred.right, out)
    elif isinstance(pred, _In):
        _operand_vars(pred.operand, out)
        for value in pred.values:
            _operand_vars(value, out)
    elif isinstance(pred, (_IsNull, _IsNotNull)):
        _operand_vars(pred.operand, out)
    elif isinstance(pred, _Present):
        target = pred.target
        refs = _slots(target) if isinstance(target, Bound) else [target]
        if not all(isinstance(ref, InstanceRef) for ref in refs):
            raise _Unsliceable(pred)
        out.update((ref, PRESENT) for ref in refs)
    else:
        raise _Unsliceable(pred)


def _operand_vars(op: Any, out: set[Var]) -> None:
    if isinstance(op, FieldDescriptor):
        out.add((op.entity_cls, op.field_name))
    elif isinstance(op, InstanceField):
        # reading an absent slot is an error, so presence is read too
        out.add((op.instance, op.field_name))
        out.add((op.instance, PRESENT))
    elif isinstance(op, (_AddExpr, _SubExpr, _MulExpr)):
        _operand_vars(op.left, out)
        _operand_vars(op.right, out)
    elif isinstance(op, _Count):
        for ref in _slots(op.variable):
            out.add((ref, PRESENT))
            _pred_vars(bind_predicate(op.predicate, op.variable, ref), out)
    elif isinstance(op, (_Sum, _Min, _Max)):
        for ref in _slots(op.variable):
            out.add((ref, PRESENT))
            _operand_vars(bind_operand(op.operand, op.variable, ref), out)
    elif isinstance(op, (Predicate, BoundField, Bound)):
        raise _Unsliceable(op)  # a predicate in operand position / unbound variable
    # anything else is a literal value (numbers, strings, enums, refs as values)


def _entity_cls(key: Any) -> type:
    return key.entity_cls if isinstance(key, InstanceRef) else key


def _target_key(effect: Any) -> Any:
    field = effect.field
    if isinstance(field, InstanceField):
        return field.instance
    if isinstance(field, FieldDescriptor):
        return field.entity_cls
    raise _Unsliceable(effect)


def _whole_slot(ref: InstanceRef) -> set[Var]:
    return {(ref, name) for name in all_fields(ref.entity_cls)} | {(ref, PRESENT)}


def _action_writes(action: Action) -> set[Var]:
    writes: set[Var] = set()
    for effect in action.effect:
        if isinstance(effect, (Set, Add, Subtract)):
            writes.add((_target_key(effect), effect.field.field_name))
        elif isinstance(effect, (Create, Delete)):
            writes |= _whole_slot(effect.target)
        else:
            raise _Unsliceable(effect)
    return writes


def _action_vars(action: Action, lock_fields: dict[type, list[str]]) -> set[Var]:
    """Everything the action's outcome depends on or changes."""
    out = _action_writes(action)
    for pred in [*action.pre, *action.post]:
        _pred_vars(pred, out)
    touched = set()
    for effect in action.effect:
        if isinstance(effect, Set):
            _operand_vars(effect.value, out)
            touched.add(_target_key(effect))
        elif isinstance(effect, (Add, Subtract)):
            _operand_vars(effect.amount, out)
            touched.add(_target_key(effect))
        elif isinstance(effect, Create):
            for value in effect.fields.values():
                _operand_vars(value, out)
        elif isinstance(effect, Delete):
            touched.add(effect.target)
    for key in touched:
        if isinstance(key, InstanceRef):
            out.add((key, PRESENT))  # presence guard
        for name in lock_fields.get(_entity_cls(key), ()):
            out.add((key, name))  # terminal lock
    for emitted in action.emits:
        if not isinstance(emitted, type):
            for value in emitted.__dict__.values():
                _operand_vars(value, out)
    return out


# ── slices ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Slice:
    """``vars is None`` means the whole model (an unsliceable property)."""

    vars: frozenset | None
    actions: tuple
    invariants: tuple

    def summary(self) -> dict:
        fields = (
            ["*"]
            if self.vars is None
            else sorted(f"{context_key_label(key)}.{name}" for key, name in self.vars)
        )
        return {"actions": len(self.actions), "invariants": len(self.invariants), "fields": fields}


class SliceAnalysis:
    """Per-spec dependency index: who writes each variable, which invariants
    read it — built once per validate() run."""

    def __init__(self, spec: Spec) -> None:
        self.spec = spec
        lock_fields: dict[type, list[str]] = {}
        for lc in spec.lifecycles:
            if lc.terminal:
                lock_fields.setdefault(lc.entity_cls, []).append(lc.field_name)
        self.whole = Slice(None, tuple(spec.actions), tuple(spec.invariants))
        # Keyed by id(); each value pins its object so the id cannot be reused by
        # another root set while this analysis lives (a reused id would hand one
        # query's roots another query's exploration).
        self._legal: dict[int, tuple[dict, bool]] = {}  # root ctx -> expanded by full model
        self._roots_keys: dict[int, tuple[list, tuple]] = {}
        # (roots, budget) -> [(slice, exploration)] explored in this run
        self.explored: dict[tuple, list] = {}
        self.covered: dict[tuple, dict] = {}  # (roots, budget) -> cover_actions result
        self._action_slices: dict[int, Slice] = {}
        self.sliceable = True
        self.action_vars: dict[int, set[Var]] = {}
        self.writers: dict[Var, list[Action]] = {}
        self.inv_vars: dict[int, set[Var]] = {}
        self.readers: dict[Var, list[Invariant]] = {}
        try:
            for action in spec.actions:
                self.action_vars[id(action)] = _action_vars(action, lock_fields)
                for var in _action_writes(action):
                    self.writers.setdefault(var, []).append(action)
            for inv in spec.invariants:
                found: set[Var] = set()
                _pred_vars(inv.expression, found)
                self.inv_vars[id(inv)] = found
                for var in found:
                    self.readers.setdefault(var, []).append(inv)
        except _Unsliceable:
            self.sliceable = False

    def predicate_slice(self, *predicates: Any) -> Slice:
        seed: set[Var] = set()
        try:
            for pred in predicates:
                _pred_vars(pred, seed)
        except _Unsliceable:
            return self.whole
        return self._close(seed, ())

    def invariant_slice(self, inv: Invariant) -> Slice:
        if not self.sliceable:
            return self.whole
        return self._close(set(self.inv_vars[id(inv)]), (), (inv,))

    def action_slice(self, action: Action) -> Slice:
        """The cone of an action itself — for its fireability and defects."""
        if not self.sliceable:
            return self.whole
        piece = self._action_slices.get(id(action))
        if piece is None:
            piece = self._close(set(self.action_vars[id(action)]), (action,))
            self._action_slices[id(action)] = piece
        return piece

    def _close(self, seed: set[Var], actions: tuple, invariants: tuple = ()) -> Slice:
        if not self.sliceable:
            return self.whole
        in_actions = {id(a) for a in actions}
        in_invariants = {id(i) for i in invariants}
        variables: set[Var] = set()
        work = list(seed)
        while work:
            var = work.pop()
            if var in variables:
                continue
            variables.add(var)
            for action in self.writers.get(var, ()):
                if id(action) not in in_actions:
                    in_actions.add(id(action))
                    work.extend(self.action_vars[id(action)])
            for inv in self.readers.get(var, ()):
                if id(inv) not in in_invariants:
                    in_invariants.add(id(inv))
                    work.extend(self.inv_vars[id(inv)])
        return Slice(
            frozenset(variables),
            tuple(a for a in self.spec.actions if id(a) in in_actions),
            tuple(i for i in self.spec.invariants if id(i) in in_invariants),
        )

    def roots_key(self, initials: list[dict]) -> tuple:
        from analint.validator.explorer import state_key

        cached = self._roots_keys.get(id(initials))
        if cached is None:
            cached = (initials, tuple(state_key(ctx) for ctx in initials))
            self._roots_keys[id(initials)] = cached
        return cached[1]

    def explorations(self) -> list:
        return [exp for runs in self.explored.values() for _, exp in runs]

    def sliced_spec(self, piece: Slice) -> Spec:
        if piece.vars is None:
            return self.spec
        return self.spec.model_copy(
            update={"actions": list(piece.actions), "invariants": list(piece.invariants)}
        )

    def project_roots(
        self, piece: Slice, initials: list[dict]
    ) -> tuple[list[dict], list[int], frozenset[int]]:
        """One representative root per projection: a legal one when there is
        any (it is expanded); otherwise an illegal one, kept but not expanded.
        Returns (roots, their 1-based numbers in ``initials``, inert positions)."""
        if piece.vars is None:
            return initials, list(range(1, len(initials) + 1)), frozenset()
        order = sorted(piece.vars, key=lambda v: (context_key_label(v[0]), v[1]))
        chosen: dict[tuple, tuple[int, bool]] = {}
        for pos, ctx in enumerate(initials):
            projection = tuple(_value(ctx, var) for var in order)
            cached = self._legal.get(id(ctx))
            if cached is None:
                cached = self._legal[id(ctx)] = (ctx, _is_legal(self.spec, ctx))
            legal = cached[1]
            if projection not in chosen or (legal and not chosen[projection][1]):
                chosen[projection] = (pos, legal)
        picks = sorted(chosen.values())
        roots = [initials[pos] for pos, _ in picks]
        numbers = [pos + 1 for pos, _ in picks]
        inert = frozenset(i for i, (_, legal) in enumerate(picks) if not legal)
        return roots, numbers, inert


def _value(ctx: dict, var: Var) -> Any:
    key, name = var
    if name == PRESENT:
        return is_present(ctx, key)
    inst = ctx.get(key)
    return None if inst is None else inst.__dict__.get(name)


def _is_legal(spec: Spec, ctx: dict) -> bool:
    """A root the full exploration would expand: every applicable invariant
    evaluates, and holds."""
    for inv in spec.invariants:
        if not invariant_is_applicable(inv, ctx):
            continue
        try:
            if not evaluate(inv.expression, ctx):
                return False
        except Exception:
            return False
    return True
