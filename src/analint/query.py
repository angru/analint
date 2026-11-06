"""Read-only queries over a built Spec — the agent-facing introspection surface.

Every function returns plain JSON-able dicts. Used by `analint show`,
`analint affects`, and the MCP server.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Create, Delete, Effect, Set, Subtract
from analint.models.entity import _MISSING, all_fields
from analint.models.event import Event
from analint.models.flow import Assert, Emitted
from analint.models.root import Spec
from analint.models.scope import FieldRef, InstanceRef, field_context_key, is_field_ref
from analint.validator.slicing import PRESENT, Var, _operand_vars, _pred_vars
from analint.validator.structural import _collect_field_refs, _describe, _describe_operand

# ── Rendering helpers ──────────────────────────────────────────────────────────


def _effect_str(effect: Any) -> str:
    if isinstance(effect, Set):
        return f"{_describe_operand(effect.field)} = {_describe_operand(effect.value)}"
    if isinstance(effect, Subtract):
        return f"{_describe_operand(effect.field)} -= {_describe_operand(effect.amount)}"
    if isinstance(effect, Add):
        return f"{_describe_operand(effect.field)} += {_describe_operand(effect.amount)}"
    if isinstance(effect, Create):
        fields = ", ".join(f"{name}={_describe_operand(v)}" for name, v in effect.fields.items())
        return f"Create({effect.target!r}{', ' + fields if fields else ''})"
    return repr(effect)


def _emit_str(emitted: type[Event] | Event) -> str:
    if isinstance(emitted, type):
        return emitted.__name__
    bound = ", ".join(f"{f}={_describe_operand(v)}" for f, v in emitted.__dict__.items())
    return f"{type(emitted).__name__}({bound})"


def _fields_of(cls: type) -> list[dict]:
    own_fields: dict = {}
    for klass in reversed(cls.__mro__):
        own_fields.update(getattr(klass, "_own_fields", {}))
    annotations: dict = {}
    for klass in reversed(cls.__mro__):
        annotations.update(getattr(klass, "__annotations__", {}))
    out = []
    for name, desc in own_fields.items():
        ann = annotations.get(name)
        entry: dict = {
            "name": name,
            "type": getattr(ann, "__name__", str(ann)) if ann is not None else None,
        }
        if desc.default is not _MISSING:
            entry["default"] = _value_str(desc.default)
        if desc.spec is not None:
            constraints: dict[str, Any] = {
                key: _value_str(value)
                for key, value in {
                    "ge": desc.spec.ge,
                    "gt": desc.spec.gt,
                    "le": desc.spec.le,
                    "lt": desc.spec.lt,
                }.items()
                if value is not None
            }
            if desc.spec.values is not None:
                constraints["values"] = [_value_str(value) for value in desc.spec.values]
            entry["constraints"] = constraints
            if desc.spec.saturate:
                entry["saturate"] = True
        if desc.lifecycle is not None:
            entry["lifecycle"] = desc.lifecycle.id
        out.append(entry)
    return out


def _value_str(value: Any) -> str:
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    return repr(value)


def _predicate_reads(predicate: Any) -> set[Var]:
    reads: set[Var] = set()
    _pred_vars(predicate, reads)
    return reads


def _action_reads(spec: Spec, action: Action) -> set[Var]:
    """Static reads, including payloads and the kernel's implicit guards.

    Reuse the slice walkers for expression/quantifier membership dependencies;
    do not use its whole-slot writes, which conservatively include deleted fields.
    """
    reads: set[Var] = set()
    frozen: set[Any] = set()
    for pred in [*action.pre, *action.post]:
        _pred_vars(pred, reads)
    for effect in action.effect:
        if isinstance(effect, (Set, Add, Subtract)) and is_field_ref(effect.field):
            target = field_context_key(effect.field)
            frozen.add(target)
            if isinstance(target, InstanceRef):
                reads.add((target, PRESENT))
            if effect.field.lifecycle is not None:
                _operand_vars(effect.field, reads)  # old state selects the allowed lifecycle edge
            if isinstance(effect, Set):
                _operand_vars(effect.value, reads)
            else:
                _operand_vars(effect.field, reads)  # old target value
                _operand_vars(effect.amount, reads)
        elif isinstance(effect, (Create, Delete)):
            reads.add((effect.target, PRESENT))
            if isinstance(effect, Create):
                for value in effect.fields.values():
                    _operand_vars(value, reads)
            else:
                frozen.add(effect.target)
    for lifecycle in spec.lifecycles:
        if lifecycle.terminal:
            for target in frozen:
                if _entity_cls(target) is lifecycle.entity_cls:
                    reads.add((target, lifecycle.field_name))
    for emitted in action.emits:
        if not isinstance(emitted, type):
            for value in emitted.__dict__.values():
                _operand_vars(value, reads)
    return reads


def _entity_cls(key: Any) -> type:
    return key.entity_cls if isinstance(key, InstanceRef) else key


def _field_refs(variables: set[Var]) -> list[FieldRef]:
    return [getattr(key, name) for key, name in variables if name != PRESENT]


def _action_writes(action: Action) -> list[tuple[FieldRef, Effect]]:
    """Field assignments, including every field initialized by Create."""
    writes: list[tuple[FieldRef, Effect]] = []
    for effect in action.effect:
        if isinstance(effect, (Set, Add, Subtract)) and is_field_ref(effect.field):
            writes.append((effect.field, effect))
        elif isinstance(effect, Create):
            writes.extend(
                (getattr(effect.target, name), effect)
                for name in all_fields(effect.target.entity_cls)
            )
    return writes


def _scenarios_of(spec: Spec, action_id: str) -> list[str]:
    return [sc.id for sc in spec.scenarios if sc.action.id == action_id]


# ── Overview ───────────────────────────────────────────────────────────────────


OVERVIEW_SCHEMA = "analint.overview/v1"
SHOW_SCHEMA = "analint.show/v1"
AFFECTS_SCHEMA = "analint.affects/v1"


def spec_overview(spec: Spec) -> dict:
    return {
        "schema": OVERVIEW_SCHEMA,
        "spec": {
            "id": spec.id,
            "name": spec.name,
            "version": spec.version,
            "description": spec.description,
        },
        "contracts": [
            {
                "id": contract.id,
                "name": contract.name,
                "version": contract.version,
            }
            for contract in spec.imports
        ],
        "entities": [e.__name__ for e in spec.entities],
        "scopes": [
            {
                "id": scope.id,
                "entity": scope.entity_cls.__name__,
                "initially_present": scope.initially_present,
                "instances": [repr(ref) for ref in scope],
            }
            for scope in spec.scopes
        ],
        "events": [e.__name__ for e in spec.events],
        "invariants": [i.id for i in spec.invariants],
        "actions": [a.id for a in spec.actions],
        "lifecycles": [lc.id for lc in spec.lifecycles],
        "flows": [f.id for f in spec.flows],
        "scenarios": [sc.id for sc in spec.scenarios],
        "queries": [q.id for q in spec.queries],
    }


# ── show <kind> <name> ─────────────────────────────────────────────────────────


def show(spec: Spec, kind: str | None = None, name: str | None = None) -> dict:
    """Unified `show`: overview (no kind), a kind's ids (kind, no name), or one
    object (kind + name). Shared by the CLI and MCP so they never diverge."""
    if kind is None:
        return spec_overview(spec)
    if name is None:
        overview = spec_overview(spec)
        key = kind if kind in overview else kind + "s"
        if key in overview:
            return {"schema": SHOW_SCHEMA, "kind": kind, "items": overview[key]}
        kinds = [k for k in overview if k not in ("schema", "spec", "contracts")]
        return {"schema": SHOW_SCHEMA, "error": f"unknown kind '{kind}'", "kinds": kinds}
    return describe(spec, kind, name)


def describe(spec: Spec, kind: str, name: str) -> dict:
    dispatch = {
        "entity": _describe_entity,
        "event": _describe_event,
        "invariant": _describe_invariant,
        "action": _describe_action,
        "lifecycle": _describe_lifecycle,
        "flow": _describe_flow,
        "scenario": _describe_scenario,
        "contract": _describe_contract,
    }
    fn = dispatch.get(kind)
    if fn is None:
        return {"schema": SHOW_SCHEMA, "error": f"unknown kind '{kind}'", "kinds": sorted(dispatch)}
    return {"schema": SHOW_SCHEMA, **fn(spec, name)}


def _describe_contract(spec: Spec, name: str) -> dict:
    contract = next((item for item in spec.imports if item.id == name), None)
    if contract is None:
        return _not_found("contract", name, [item.id for item in spec.imports])
    return {
        "kind": "contract",
        "id": contract.id,
        "name": contract.name,
        "version": contract.version,
        "description": contract.description,
        "entities": [entity.__name__ for entity in contract.entities],
        "scopes": [scope.id for scope in contract.scopes],
        "events": [event.__name__ for event in contract.events],
        "invariants": [invariant.id for invariant in contract.invariants],
        "actions": [action.id for action in contract.actions],
        "lifecycles": [lifecycle.id for lifecycle in contract.lifecycles],
        "flows": [flow.id for flow in contract.flows],
        "scenarios": [scenario.id for scenario in contract.scenarios],
        "queries": [query.id for query in contract.queries],
    }


def _not_found(kind: str, name: str, known: list[str]) -> dict:
    return {"error": f"{kind} '{name}' not found", "known": known}


def _describe_entity(spec: Spec, name: str) -> dict:
    cls = next((e for e in spec.entities if e.__name__ == name), None)
    if cls is None:
        return _not_found("entity", name, [e.__name__ for e in spec.entities])
    read_by = sorted(
        {
            a.id
            for a in spec.actions
            if any(_entity_cls(key) is cls for key, _ in _action_reads(spec, a))
        }
    )
    written_by = sorted(
        {
            a.id
            for a in spec.actions
            if any(field.entity_cls is cls for field, _ in _action_writes(a))
            or any(isinstance(e, (Create, Delete)) and e.target.entity_cls is cls for e in a.effect)
        }
    )
    return {
        "kind": "entity",
        "name": name,
        "fields": _fields_of(cls),
        "scopes": [
            {
                "id": scope.id,
                "instances": [repr(ref) for ref in scope],
                "initially_present": scope.initially_present,
            }
            for scope in spec.scopes
            if scope.entity_cls is cls
        ],
        "lifecycles": [lc.id for lc in spec.lifecycles if lc.entity_cls is cls],
        "read_by": read_by,
        "written_by": written_by,
        "presence_read_by": sorted(
            a.id
            for a in spec.actions
            if any(key.entity_cls is cls for key, name in _action_reads(spec, a) if name == PRESENT)
        ),
        "presence_written_by": sorted(
            a.id
            for a in spec.actions
            if any(isinstance(e, (Create, Delete)) and e.target.entity_cls is cls for e in a.effect)
        ),
        "invariants": [
            i.id
            for i in spec.invariants
            if any(_entity_cls(key) is cls for key, _ in _predicate_reads(i.expression))
        ],
    }


def _describe_event(spec: Spec, name: str) -> dict:
    cls = next((e for e in spec.events if e.__name__ == name), None)
    if cls is None:
        return _not_found("event", name, [e.__name__ for e in spec.events])
    emitted_by = []
    for a in spec.actions:
        for emitted in a.emits:
            if (emitted if isinstance(emitted, type) else type(emitted)) is cls:
                emitted_by.append({"action": a.id, "payload": _emit_str(emitted)})
    return {
        "kind": "event",
        "name": name,
        "fields": _fields_of(cls),
        "emitted_by": emitted_by,
    }


def _describe_invariant(spec: Spec, name: str) -> dict:
    inv = next((i for i in spec.invariants if i.id == name), None)
    if inv is None:
        return _not_found("invariant", name, [i.id for i in spec.invariants])
    return {
        "kind": "invariant",
        "id": inv.id,
        "label": inv.label,
        "expression": _describe(inv.expression),
        "entities": sorted(
            {_entity_cls(key).__name__ for key, _ in _predicate_reads(inv.expression)}
        ),
    }


def _describe_action(spec: Spec, name: str) -> dict:
    action = next((a for a in spec.actions if a.id == name), None)
    if action is None:
        return _not_found("action", name, [a.id for a in spec.actions])
    return {
        "kind": "action",
        "id": action.id,
        "name": action.name,
        "description": action.description,
        "pre": [_describe(p) for p in action.pre],
        "effect": [_effect_str(e) for e in action.effect],
        "post": [_describe(p) for p in action.post],
        "emits": [_emit_str(e) for e in action.emits],
        "flows": [f.id for f in spec.flows if _flow_uses(f, action.id)],
        "scenarios": _scenarios_of(spec, action.id),
        "tags": list(action.tags),
    }


def _describe_lifecycle(spec: Spec, name: str) -> dict:
    lc = next((x for x in spec.lifecycles if x.id == name), None)
    if lc is None:
        return _not_found("lifecycle", name, [x.id for x in spec.lifecycles])
    reachable = lc.reachable_states()
    out = {
        "kind": "lifecycle",
        "id": lc.id,
        "field": _describe_operand(lc.field),
        "initial": _value_str(lc.initial),
        "transitions": [
            {"from": _value_str(source), "to": [_value_str(state) for state in targets]}
            for source, targets in lc.transitions.items()
        ],
        "terminal": [_value_str(s) for s in lc.terminal],
        "reachable": [_value_str(s) for s in reachable],
    }
    state_type = type(lc.initial)
    if issubclass(state_type, Enum):
        out["unreachable"] = [_value_str(s) for s in state_type if s not in reachable]
    return out


def _describe_flow(spec: Spec, name: str) -> dict:
    flow = next((f for f in spec.flows if f.id == name), None)
    if flow is None:
        return _not_found("flow", name, [f.id for f in spec.flows])
    return {
        "kind": "flow",
        "id": flow.id,
        "description": flow.description,
        "steps": [_flow_step_str(s) for s in flow.steps],
    }


def _flow_uses(flow: Any, action_id: str) -> bool:
    return any(isinstance(s, Action) and s.id == action_id for s in flow.steps)


def _flow_step_str(step: Any) -> str:
    if isinstance(step, Action):
        return step.id
    if isinstance(step, Assert):
        return f"assert: {_describe(step.predicate)}"
    if isinstance(step, Emitted):
        return f"emitted: {step.event_cls.__name__}"
    return repr(step)


def _describe_scenario(spec: Spec, name: str) -> dict:
    sc = next((s for s in spec.scenarios if s.id == name), None)
    if sc is None:
        return _not_found("scenario", name, [s.id for s in spec.scenarios])
    return {
        "kind": "scenario",
        "id": sc.id,
        "name": sc.name,
        "action": sc.action.id,
        "given": [repr(inst) for inst in sc.given],
        "then": [repr(t) for t in sc.then],
        "expected": sc.expected.value,
        "tags": list(sc.tags),
    }


# ── affects <target> ───────────────────────────────────────────────────────────


def affects(spec: Spec, target: str) -> dict:
    """Impact analysis: what touches this field / entity / action.

    Target forms: 'Entity.field', 'Entity' (or event name), or an action id.
    """
    return {"schema": AFFECTS_SCHEMA, **_affects(spec, target)}


def _affects(spec: Spec, target: str) -> dict:
    if "." in target:
        entity_name, field_name = target.split(".", 1)
        return _affects_field(spec, entity_name, field_name)
    if any(e.__name__ == target for e in list(spec.entities) + list(spec.events)):
        return _affects_entity(spec, target)
    if any(a.id == target for a in spec.actions):
        return _affects_action(spec, target)
    return {
        "error": f"'{target}' is not a known Entity.field, entity, event, or action id",
        "entities": [e.__name__ for e in spec.entities],
        "actions": [a.id for a in spec.actions],
    }


def _affects_field(spec: Spec, entity_name: str, field_name: str) -> dict:
    def _matches(ref: Any) -> bool:
        return ref.entity_cls.__name__ == entity_name and ref.field_name == field_name

    written_by = []
    for a in spec.actions:
        for field, effect in _action_writes(a):
            if _matches(field):
                entry = {"action": a.id, "effect": _effect_str(effect)}
                if isinstance(effect, Create):
                    entry["initialization"] = (
                        "explicit" if field_name in effect.fields else "default"
                    )
                written_by.append(entry)

    read_by = sorted(
        a.id for a in spec.actions if any(_matches(r) for r in _field_refs(_action_reads(spec, a)))
    )
    invariants = [
        i.id for i in spec.invariants if any(_matches(r) for r in _collect_field_refs(i.expression))
    ]
    lifecycles = [lc.id for lc in spec.lifecycles if _matches(lc.field)]

    event_bindings = []
    for a in spec.actions:
        for emitted in a.emits:
            if isinstance(emitted, type):
                continue
            for f, v in emitted.__dict__.items():
                reads: set[Var] = set()
                _operand_vars(v, reads)
                if any(_matches(r) for r in _field_refs(reads)):
                    event_bindings.append(
                        {"action": a.id, "event": type(emitted).__name__, "payload_field": f}
                    )

    impacted_actions = sorted({w["action"] for w in written_by} | set(read_by))
    return {
        "kind": "field",
        "target": f"{entity_name}.{field_name}",
        "written_by": written_by,
        "read_by": read_by,
        "invariants": invariants,
        "lifecycles": lifecycles,
        "event_bindings": event_bindings,
        "scenarios": sorted({sc.id for sc in spec.scenarios if sc.action.id in impacted_actions}),
    }


def _affects_entity(spec: Spec, name: str) -> dict:
    cls = next((e for e in list(spec.entities) + list(spec.events) if e.__name__ == name), None)
    described = (_describe_entity if cls in spec.entities else _describe_event)(spec, name)
    described["kind"] = "affects"
    return described


def _affects_action(spec: Spec, action_id: str) -> dict:
    action = next(a for a in spec.actions if a.id == action_id)
    reads = _action_reads(spec, action)
    return {
        "kind": "action-impact",
        "target": action_id,
        "reads": sorted({_describe_operand(r) for r in _field_refs(reads)}),
        "writes": [_effect_str(e) for e in action.effect],
        "presence_reads": sorted(repr(key) for key, name in reads if name == PRESENT),
        "presence_writes": [
            {"instance": repr(e.target), "present": isinstance(e, Create)}
            for e in action.effect
            if isinstance(e, (Create, Delete))
        ],
        "emits": [_emit_str(e) for e in action.emits],
        "flows": [f.id for f in spec.flows if _flow_uses(f, action_id)],
        "scenarios": _scenarios_of(spec, action_id),
    }
