"""Export an analint model (or one property's slice) to TLA+ for TLC (research/36 R6).

The generated module is the analint transition system, not a paraphrase of it:

- one variable per context key (singleton entity or Scope slot); a slot is a
  record with ``present__`` and holds canonical values while absent, exactly as
  analint's state key ignores absent fields;
- ``Init`` lists analint's root states literally;
- one action per concrete (Param-expanded) action: ``pre`` guards, presence
  guards, the terminal lock, then simultaneous effects computed from the
  pre-state; saturating ``Field`` bounds clamp;
- a transition analint would report as a *defect* (a hard ``Field`` bound, an
  undeclared lifecycle edge, a false ``post``) is not a transition here either,
  and ``NoDefect_<action>`` invariants report it;
- the slice's invariants are TLC's ``CONSTRAINT``: a state breaking one is kept
  and checked but not expanded — analint's pruning — and so are inert roots;
- the property under check is the ``Target`` invariant.

What TLA+ cannot mirror is refused (``ExportError``) rather than approximated:
reading a Scope slot that may be absent where analint would raise an evaluation
error, ``Min``/``Max`` (an error on an empty scope), event-payload guards, and
values other than bools, ints, strings, enums, references and ``None``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Create, Delete, Set, Subtract
from analint.models.entity import _MISSING, FieldDescriptor, all_fields
from analint.models.expr import _AddExpr, _MulExpr, _SubExpr
from analint.models.key import Key
from analint.models.predicate import (
    _And,
    _BinaryComparison,
    _Eq,
    _Gt,
    _Gte,
    _Implies,
    _In,
    _IsNotNull,
    _IsNull,
    _Lt,
    _Lte,
    _Ne,
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
from analint.models.scope import InstanceField, InstanceRef, context_key_label

PRESENT = "present__"
NULL = '"__null__"'


class ExportError(Exception):
    """The model uses something TLA+ cannot mirror exactly."""


@dataclass
class Target:
    """The property TLC checks as ``Target``.

    ``kind``: ``holds`` (an invariant: where applicable, it holds), ``never``
    (the predicate never holds — Unreachable; a violation of ``never`` is a
    Reachable witness), ``always`` (AlwaysHolds), ``applicable`` (the
    invariant's referenced slots are never all present — its violation shows
    the invariant is evaluable somewhere)."""

    kind: str
    predicate: Any


@dataclass
class TlaExport:
    module_name: str
    module: str
    config: str
    actions: dict[str, str] = field(default_factory=dict)  # TLA name → action id


# ── values and names ─────────────────────────────────────────────────────────


def _literal(value: Any) -> str:
    if value is None:
        return NULL
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    # Scalar Enum subclasses compare as their underlying str/int in Python.
    # Keep that equality in TLC; only plain Enum members have symbolic identity.
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, Enum):
        if isinstance(value, float):
            raise ExportError(f"value {value!r} has no TLA+ form")
        return json.dumps(f"{type(value).__name__}.{value.name}")
    if isinstance(value, InstanceRef):
        return json.dumps(f"ref:{context_key_label(value)}")
    if isinstance(value, type):
        return json.dumps(f"cls:{value.__name__}")
    raise ExportError(f"value {value!r} has no TLA+ form")


def _ident(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", text)


def _field(name: str) -> str:
    return f"f_{name}"


class _Model:
    """Layout, names and the presence facts the renderer needs."""

    def __init__(self, spec: Spec, roots: list[dict]) -> None:
        self.spec = spec
        self.keys = sorted(roots[0], key=context_key_label)
        if any(sorted(ctx, key=context_key_label) != self.keys for ctx in roots):
            raise ExportError("roots with different context keys")
        self.var: dict[Any, str] = {}
        for key in self.keys:
            name = "v_" + _ident(context_key_label(key))
            while name in self.var.values():
                name += "_"
            self.var[key] = name
        self.fields = {
            key: sorted(all_fields(key.entity_cls if isinstance(key, InstanceRef) else key))
            for key in self.keys
        }
        # a slot may be absent if some root lacks it or some action creates/deletes it
        self.may_be_absent = {
            key
            for key in self.keys
            if isinstance(key, InstanceRef)
            and any(not ctx[key].__dict__.get("_analint_present", True) for ctx in roots)
        }
        for action in spec.actions:
            for effect in action.effect:
                if isinstance(effect, (Create, Delete)):
                    self.may_be_absent.add(effect.target)

    def record(self, key: Any, inst: Any) -> str:
        values = inst.__dict__
        parts = []
        if isinstance(key, InstanceRef):
            present = values.get("_analint_present", True)
            parts.append(f"{PRESENT} |-> {_literal(present)}")
            if not present:
                return self.absent(key)
        parts += [f"{_field(f)} |-> {_literal(values.get(f))}" for f in self.fields[key]]
        return "[" + ", ".join(parts) + "]"

    def absent(self, key: Any) -> str:
        parts = [f"{PRESENT} |-> FALSE"] + [f"{_field(f)} |-> {NULL}" for f in self.fields[key]]
        return "[" + ", ".join(parts) + "]"


# ── expressions ──────────────────────────────────────────────────────────────


class _Renderer:
    """Renders predicates/operands over records named in ``rec`` (key → TLA
    expression of that key's record in the evaluated state)."""

    def __init__(self, model: _Model, rec: dict[Any, str], safe: set) -> None:
        self.model = model
        self.rec = rec
        self.safe = safe  # slots known present here (reading them cannot fail)

    def read(self, key: Any, name: str) -> str:
        if key not in self.rec:
            raise ExportError(f"reads {context_key_label(key)}, which is not in the state")
        if (
            isinstance(key, InstanceRef)
            and key in self.model.may_be_absent
            and key not in self.safe
        ):
            raise ExportError(
                f"reads {context_key_label(key)}.{name} where the slot may be absent "
                f"(analint raises an evaluation error there); guard it with Present first"
            )
        return f"{self.rec[key]}.{_field(name)}"

    def operand(self, op: Any) -> str:
        if isinstance(op, Key):
            if not isinstance(op.target, InstanceRef):
                raise ExportError(f"unbound Key target {op.target!r}")
            return _literal(op.target.key)
        if isinstance(op, FieldDescriptor):
            return self.read(op.entity_cls, op.field_name)
        if isinstance(op, InstanceField):
            return self.read(op.instance, op.field_name)
        if isinstance(op, (_AddExpr, _SubExpr, _MulExpr)):
            sign = {_AddExpr: "+", _SubExpr: "-", _MulExpr: "*"}[type(op)]
            return f"({self.operand(op.left)} {sign} {self.operand(op.right)})"
        if isinstance(op, _Count):
            terms = [
                f"(IF {self.present(ref)} /\\ {self.bound(ref).pred(bind_predicate(op.predicate, op.variable, ref))} THEN 1 ELSE 0)"
                for ref in op.variable.scope
            ]
            return "(" + " + ".join(terms or ["0"]) + ")"
        if isinstance(op, _Sum):
            terms = [
                f"(IF {self.present(ref)} THEN {self.bound(ref).operand(bind_operand(op.operand, op.variable, ref))} ELSE 0)"
                for ref in op.variable.scope
            ]
            return "(" + " + ".join(terms or ["0"]) + ")"
        if isinstance(op, (_Min, _Max)):
            raise ExportError("Min/Max (an evaluation error on an empty scope) is not exported")
        if isinstance(op, (BoundField, Bound)):
            raise ExportError(f"unbound quantifier variable {op!r}")
        return _literal(op)

    def present(self, ref: InstanceRef) -> str:
        if ref not in self.rec:
            raise ExportError(f"reads {context_key_label(ref)}, which is not in the state")
        return f"{self.rec[ref]}.{PRESENT}"

    def bound(self, ref: InstanceRef) -> _Renderer:
        """Inside a quantifier body the bound slot is present by construction."""
        return _Renderer(self.model, self.rec, self.safe | {ref})

    def pred(self, pred: Any) -> str:
        if isinstance(pred, _And):
            # analint short-circuits left to right: a Present conjunct makes
            # later reads of its slot safe
            parts, safe = [], set(self.safe)
            for e in pred.exprs:
                parts.append(_Renderer(self.model, self.rec, set(safe)).pred(e))
                safe |= _asserted(e)
            return "(" + " /\\ ".join(parts) + ")" if parts else "TRUE"
        if isinstance(pred, _Or):
            return (
                "(" + " \\/ ".join(self.pred(e) for e in pred.exprs) + ")"
                if pred.exprs
                else "FALSE"
            )
        if isinstance(pred, _Not):
            return f"~{self.pred(pred.expr)}"
        if isinstance(pred, _Implies):
            right = _Renderer(self.model, self.rec, self.safe | _asserted(pred.left))
            return f"({self.pred(pred.left)} => {right.pred(pred.right)})"
        if isinstance(pred, _ForAll):
            terms = [
                f"({self.present(ref)} => {self.bound(ref).pred(bind_predicate(pred.predicate, pred.variable, ref))})"
                for ref in pred.variable.scope
            ]
            return "(" + " /\\ ".join(terms or ["TRUE"]) + ")"
        if isinstance(pred, _Exists):
            terms = [
                f"({self.present(ref)} /\\ {self.bound(ref).pred(bind_predicate(pred.predicate, pred.variable, ref))})"
                for ref in pred.variable.scope
            ]
            return "(" + " \\/ ".join(terms or ["FALSE"]) + ")"
        if isinstance(pred, _Present):
            if not isinstance(pred.target, InstanceRef):
                raise ExportError(f"Present over {pred.target!r}")
            return self.present(pred.target)
        if isinstance(pred, _BinaryComparison):
            op = {_Eq: "=", _Ne: "#", _Gt: ">", _Gte: ">=", _Lt: "<", _Lte: "<="}.get(type(pred))
            if op is None:
                raise ExportError(f"comparison {type(pred).__name__}")
            return f"({self.operand(pred.left)} {op} {self.operand(pred.right)})"
        if isinstance(pred, _In):
            values = ", ".join(self.operand(v) for v in pred.values)
            return f"({self.operand(pred.operand)} \\in {{{values}}})"
        if isinstance(pred, _IsNull):
            return f"({self.operand(pred.operand)} = {NULL})"
        if isinstance(pred, _IsNotNull):
            return f"({self.operand(pred.operand)} # {NULL})"
        if isinstance(pred, bool):
            return "TRUE" if pred else "FALSE"
        raise ExportError(f"predicate node {type(pred).__name__} is not exported")


def _asserted(pred: Any) -> set:
    """Slots a true ``pred`` proves present (top-level Present conjuncts)."""
    if isinstance(pred, _Present) and isinstance(pred.target, InstanceRef):
        return {pred.target}
    if isinstance(pred, _And):
        return set().union(*(_asserted(e) for e in pred.exprs))
    return set()


def _outside_refs(pred: Any) -> list[Any]:
    """Field references outside quantifiers/aggregates — those an invariant
    needs present to be applicable (``state_checks.invariant_is_applicable``)."""
    out: list[Any] = []

    def operand(op: Any) -> None:
        if isinstance(op, (FieldDescriptor, InstanceField)):
            out.append(op)
        elif isinstance(op, (_AddExpr, _SubExpr, _MulExpr)):
            operand(op.left)
            operand(op.right)

    def walk(p: Any) -> None:
        if isinstance(p, (_And, _Or)):
            for e in p.exprs:
                walk(e)
        elif isinstance(p, _Not):
            walk(p.expr)
        elif isinstance(p, _Implies):
            walk(p.left)
            walk(p.right)
        elif isinstance(p, _BinaryComparison):
            operand(p.left)
            operand(p.right)
        elif isinstance(p, _In):
            operand(p.operand)
            for v in p.values:
                operand(v)
        elif isinstance(p, (_IsNull, _IsNotNull)):
            operand(p.operand)

    walk(pred)
    return out


def _guarded(model: _Model, rec: dict[Any, str], pred: Any) -> str:
    """``applicable => pred``: what analint checks for an invariant. Under the
    implication the referenced slots are present, so reading them is safe."""
    safe = {r.instance for r in _outside_refs(pred) if isinstance(r, InstanceField)}
    return f"({_applicable(model, rec, pred)} => {_Renderer(model, rec, safe).pred(pred)})"


def _applicable(model: _Model, rec: dict[Any, str], pred: Any) -> str:
    terms = []
    for ref in _outside_refs(pred):
        key = ref.instance if isinstance(ref, InstanceField) else ref.entity_cls
        if key not in rec:
            return "FALSE"
        if isinstance(key, InstanceRef):
            terms.append(f"{rec[key]}.{PRESENT}")
    return "(" + " /\\ ".join(dict.fromkeys(terms)) + ")" if terms else "TRUE"


# ── actions ──────────────────────────────────────────────────────────────────


def _clamp(expr: str, spec: Any) -> str:
    if spec.ge is not None:
        expr = f"(IF {expr} < {_literal(spec.ge)} THEN {_literal(spec.ge)} ELSE {expr})"
    if spec.le is not None:
        expr = f"(IF {expr} > {_literal(spec.le)} THEN {_literal(spec.le)} ELSE {expr})"
    return expr


def _bounds(expr: str, spec: Any) -> list[str]:
    if spec is None or not spec.has_constraints():
        return []
    out = []
    if spec.values is not None:
        out.append(f"({expr} \\in {{{', '.join(_literal(v) for v in spec.values)}}})")
    for attr, op in (("ge", ">="), ("gt", ">"), ("le", "<="), ("lt", "<")):
        bound = getattr(spec, attr, None)
        if bound is not None:
            out.append(f"({expr} {op} {_literal(bound)})")
    return out


def _target_key(effect: Any) -> Any:
    f = effect.field
    return f.instance if isinstance(f, InstanceField) else f.entity_cls


def _action_defs(model: _Model, action: Action, name: str) -> tuple[list[str], str]:
    """(definitions, defect invariant name) for one action."""
    spec = model.spec
    pre_rec = dict(model.var)
    if any(_foreign(pred, model) for pred in action.pre):
        raise ExportError(f"'{action.id}' reads an event payload (not part of the state)")

    # pre guards in order: a Present guard makes later reads of that slot safe
    safe: set = set()
    guards: list[str] = []
    for pred in action.pre:
        guards.append(_Renderer(model, pre_rec, set(safe)).pred(pred))
        if isinstance(pred, _Present) and isinstance(pred.target, InstanceRef):
            safe.add(pred.target)

    touched: dict[Any, dict[str, str]] = {}
    created: dict[Any, Any] = {}
    deleted: set = set()
    for effect in action.effect:
        if isinstance(effect, (Set, Add, Subtract)):
            touched.setdefault(_target_key(effect), {})
        elif isinstance(effect, Create):
            created[effect.target] = effect
        elif isinstance(effect, Delete):
            deleted.add(effect.target)
    # presence guards (the kernel rejects before any effect)
    for key in touched:
        if isinstance(key, InstanceRef):
            guards.append(f"{model.var[key]}.{PRESENT}")
    for key in created:
        guards.append(f"~{model.var[key]}.{PRESENT}")
    for key in deleted:
        guards.append(f"{model.var[key]}.{PRESENT}")
    # terminal lock: a touched or deleted entity in a terminal state is frozen
    rhs_safe = safe | {k for k in touched if isinstance(k, InstanceRef)} | deleted
    for key in [*touched, *deleted]:
        cls = key.entity_cls if isinstance(key, InstanceRef) else key
        for lc in spec.lifecycles:
            if lc.terminal and lc.entity_cls is cls:
                terminal = ", ".join(_literal(t) for t in lc.terminal)
                guards.append(f"~({model.var[key]}.{_field(lc.field_name)} \\in {{{terminal}}})")

    # simultaneous effects: every right-hand side over the pre-state
    render = _Renderer(model, pre_rec, rhs_safe)
    for effect in action.effect:
        if isinstance(effect, Set):
            touched[_target_key(effect)][effect.field.field_name] = render.operand(effect.value)
        elif isinstance(effect, (Add, Subtract)):
            current = render.operand(effect.field)
            sign = "+" if isinstance(effect, Add) else "-"
            touched[_target_key(effect)][effect.field.field_name] = (
                f"({current} {sign} {render.operand(effect.amount)})"
            )

    defs: list[str] = []
    post_rec = dict(model.var)
    ok: list[str] = []
    new_values: dict[Any, dict[str, str]] = {}
    for key, updates in touched.items():
        cls = key.entity_cls if isinstance(key, InstanceRef) else key
        descs = all_fields(cls)
        fields_new: dict[str, str] = {}
        for fname, expr in updates.items():
            fspec = descs[fname].spec
            if fspec is not None and fspec.saturate:
                expr = _clamp(expr, fspec)
            else:
                ok += _bounds(expr, fspec)
            fields_new[fname] = expr
        new_values[key] = fields_new
        rec_name = f"{name}_post_{model.var[key]}"
        excepts = ", ".join(f"!.{_field(f)} = {e}" for f, e in fields_new.items())
        defs.append(f"{rec_name} == [{model.var[key]} EXCEPT {excepts}]")
        post_rec[key] = rec_name
    for key, effect in created.items():
        descs = all_fields(key.entity_cls)
        parts = [f"{PRESENT} |-> TRUE"]
        for fname in model.fields[key]:
            if fname in effect.fields:
                expr = render.operand(effect.fields[fname])
            elif descs[fname].default is not _MISSING:
                expr = _literal(descs[fname].default)
            else:
                raise ExportError(f"Create({context_key_label(key)}) leaves '{fname}' unset")
            fspec = descs[fname].spec
            if fspec is not None and fspec.saturate:
                expr = _clamp(expr, fspec)
            else:
                ok += _bounds(expr, fspec)
            parts.append(f"{_field(fname)} |-> {expr}")
        rec_name = f"{name}_post_{model.var[key]}"
        defs.append(f"{rec_name} == [{', '.join(parts)}]")
        post_rec[key] = rec_name
    for key in deleted:
        rec_name = f"{name}_post_{model.var[key]}"
        defs.append(f"{rec_name} == {model.absent(key)}")
        post_rec[key] = rec_name

    # declared lifecycle edges for every changed field of a present entity
    for key, fields_new in new_values.items():
        if key in created or key in deleted:
            continue
        cls = key.entity_cls if isinstance(key, InstanceRef) else key
        for lc in spec.lifecycles:
            if lc.entity_cls is cls and lc.field_name in fields_new:
                old = f"{model.var[key]}.{_field(lc.field_name)}"
                new = f"{post_rec[key]}.{_field(lc.field_name)}"
                edges = ", ".join(
                    f"<<{_literal(src)}, {_literal(dst)}>>"
                    for src, dsts in lc.transitions.items()
                    for dst in dsts
                )
                ok.append(f"({new} = {old} \\/ <<{old}, {new}>> \\in {{{edges}}})")

    post_safe = rhs_safe | set(created)
    ok += [_Renderer(model, post_rec, post_safe).pred(pred) for pred in action.post]
    for emitted in action.emits:  # an unmaterialisable payload is a defect: refuse
        if not isinstance(emitted, type):
            for value in emitted.__dict__.values():
                _Renderer(model, post_rec, post_safe).operand(value)

    enabled = " /\\ ".join(guards) or "TRUE"
    accepted = " /\\ ".join(ok) or "TRUE"
    defs.append(f"{name}_enabled == {enabled}")
    defs.append(f"{name}_ok == {accepted}")
    changed = [model.var[k] for k in model.keys if k in post_rec and post_rec[k] != model.var[k]]
    primes = [f"{model.var[k]}' = {post_rec[k]}" for k in model.keys if model.var[k] in changed]
    unchanged = [model.var[k] for k in model.keys if model.var[k] not in changed]
    body = [f"{name}_enabled", f"{name}_ok", *primes]
    if unchanged:
        body.append(f"UNCHANGED <<{', '.join(unchanged)}>>")
    defs.append(f"{name} == " + " /\\ ".join(body))
    defect = f"NoDefect_{name}"
    defs.append(f"{defect} == Legal => ({name}_enabled => {name}_ok)")
    return defs, defect


def _foreign(pred: Any, model: _Model) -> bool:
    from analint.validator.structural import _collect_field_refs

    state = {k if isinstance(k, type) else k.entity_cls for k in model.keys}
    return any(ref.entity_cls not in state for ref in _collect_field_refs(pred))


# ── module ───────────────────────────────────────────────────────────────────


def export_tla(
    spec: Spec,
    roots: list[dict],
    *,
    target: Target,
    inert: frozenset[int] = frozenset(),
    module_name: str = "analint_export",
) -> TlaExport:
    """The TLA+ module and TLC configuration of ``spec`` explored from ``roots``
    (analint contexts), checking ``target``. Raises ``ExportError`` for what
    cannot be mirrored exactly."""
    if not roots:
        raise ExportError("no initial state")
    model = _Model(spec, roots)
    rec = dict(model.var)
    lines = [f"---- MODULE {module_name} ----", "EXTENDS Integers, TLC"]
    lines.append(f"VARIABLES {', '.join(model.var[k] for k in model.keys)}")
    lines.append(f"vars == <<{', '.join(model.var[k] for k in model.keys)}>>")

    def state(ctx: dict) -> str:
        return "<<" + ", ".join(model.record(k, ctx[k]) for k in model.keys) + ">>"

    root_states = [state(ctx) for ctx in roots]
    lines.append(f"Roots == {{{', '.join(dict.fromkeys(root_states))}}}")
    assign = " /\\ ".join(f"{model.var[k]} = r[{i}]" for i, k in enumerate(model.keys, start=1))
    lines.append(f"Init == \\E r \\in Roots: {assign}")
    inert_states = sorted({root_states[i] for i in inert})
    legal = [_guarded(model, rec, inv.expression) for inv in spec.invariants]
    if inert_states:
        legal.append(f"~(vars \\in {{{', '.join(inert_states)}}})")
    lines.append(f"Legal == {' /\\ '.join(legal) or 'TRUE'}")

    names: dict[str, str] = {}
    defects: list[str] = []
    for i, action in enumerate(spec.actions):
        name = f"A{i}_{_ident(action.id)}"[:120]
        defs, defect = _action_defs(model, action, name)
        lines += defs
        names[name] = action.id
        defects.append(defect)
    lines.append(f"Next == {' \\/ '.join(names) or 'FALSE'}")

    pred = target.predicate
    if target.kind == "holds":
        body = _guarded(model, rec, pred)
    elif target.kind == "applicable":
        body = f"~{_applicable(model, rec, pred)}"
    elif target.kind == "never":
        body = f"~{_Renderer(model, rec, set()).pred(pred)}"
    elif target.kind == "always":
        body = _Renderer(model, rec, set()).pred(pred)
    else:
        raise ExportError(f"unknown target kind {target.kind}")
    lines.append(f"Target == {body}")
    lines.append("====")

    config = ["INIT Init", "NEXT Next", "CONSTRAINT Legal", "INVARIANT Target"]
    config += [f"INVARIANT {d}" for d in defects]
    config.append("CHECK_DEADLOCK FALSE")
    return TlaExport(module_name, "\n".join(lines) + "\n", "\n".join(config) + "\n", names)
