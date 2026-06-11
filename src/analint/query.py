"""Read-only queries over a built Spec — the agent-facing introspection surface.

Every function returns plain JSON-able dicts. Used by `analint show`,
`analint affects`, and the MCP server.
"""
from __future__ import annotations

from enum import Enum

from analint.models.effect import Add, Set, Subtract
from analint.models.entity import FieldDescriptor, _MISSING
from analint.models.root import Spec
from analint.validator.structural import _collect_field_refs, _describe, _describe_operand


# ── Rendering helpers ──────────────────────────────────────────────────────────

def _effect_str(effect) -> str:
    field = _describe_operand(effect.field)
    if isinstance(effect, Set):
        return f"{field} = {_describe_operand(effect.value)}"
    if isinstance(effect, Subtract):
        return f"{field} -= {_describe_operand(effect.amount)}"
    if isinstance(effect, Add):
        return f"{field} += {_describe_operand(effect.amount)}"
    return repr(effect)


def _emit_str(emitted) -> str:
    if isinstance(emitted, type):
        return emitted.__name__
    bound = ", ".join(f"{f}={_bind_str(v)}" for f, v in emitted.__dict__.items())
    return f"{type(emitted).__name__}({bound})"


def _bind_str(value) -> str:
    return _describe_operand(value) if isinstance(value, FieldDescriptor) else repr(value)


def _fields_of(cls) -> list[dict]:
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
            entry["constraints"] = {
                key: _value_str(value)
                for key, value in {
                    "ge": desc.spec.ge,
                    "gt": desc.spec.gt,
                    "le": desc.spec.le,
                    "lt": desc.spec.lt,
                }.items()
                if value is not None
            }
            if desc.spec.saturate:
                entry["saturate"] = True
        if desc.lifecycle is not None:
            entry["lifecycle"] = desc.lifecycle.id
        out.append(entry)
    return out


def _value_str(value) -> str:
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    return repr(value)


def _action_refs(action) -> list[FieldDescriptor]:
    refs: list[FieldDescriptor] = []
    for pred in list(action.pre) + list(action.post):
        refs.extend(_collect_field_refs(pred))
    return refs


def _action_writes(action) -> list:
    return [e for e in action.effect
            if isinstance(e, (Set, Subtract, Add)) and isinstance(e.field, FieldDescriptor)]


def _scenarios_of(spec: Spec, action_id: str) -> list[str]:
    return [sc.id for sc in spec.scenarios if sc.action.id == action_id]


# ── Overview ───────────────────────────────────────────────────────────────────

def spec_overview(spec: Spec) -> dict:
    return {
        "spec": {"id": spec.id, "name": spec.name,
                 "version": spec.version, "description": spec.description},
        "entities": [e.__name__ for e in spec.entities],
        "actors": [a.__name__ for a in spec.actors],
        "events": [e.__name__ for e in spec.events],
        "invariants": [i.id for i in spec.invariants],
        "actions": [a.id for a in spec.actions],
        "lifecycles": [lc.id for lc in spec.lifecycles],
        "flows": [f.id for f in spec.flows],
        "scenarios": [sc.id for sc in spec.scenarios],
        "queries": [q.id for q in spec.queries],
    }


# ── show <kind> <name> ─────────────────────────────────────────────────────────

def describe(spec: Spec, kind: str, name: str) -> dict:
    dispatch = {
        "entity": _describe_entity,
        "actor": _describe_actor,
        "event": _describe_event,
        "invariant": _describe_invariant,
        "action": _describe_action,
        "lifecycle": _describe_lifecycle,
        "flow": _describe_flow,
        "scenario": _describe_scenario,
    }
    fn = dispatch.get(kind)
    if fn is None:
        return {"error": f"unknown kind '{kind}'", "kinds": sorted(dispatch)}
    return fn(spec, name)


def _not_found(kind: str, name: str, known: list[str]) -> dict:
    return {"error": f"{kind} '{name}' not found", "known": known}


def _describe_entity(spec: Spec, name: str) -> dict:
    cls = next((e for e in spec.entities if e.__name__ == name), None)
    if cls is None:
        return _not_found("entity", name, [e.__name__ for e in spec.entities])
    read_by = sorted({a.id for a in spec.actions
                      if any(r.entity_cls is cls for r in _action_refs(a))})
    written_by = sorted({a.id for a in spec.actions
                         if any(w.field.entity_cls is cls for w in _action_writes(a))})
    return {
        "kind": "entity",
        "name": name,
        "fields": _fields_of(cls),
        "lifecycles": [lc.id for lc in spec.lifecycles if lc.entity_cls is cls],
        "read_by": read_by,
        "written_by": written_by,
        "invariants": [i.id for i in spec.invariants
                       if any(r.entity_cls is cls for r in _collect_field_refs(i.expression))],
    }


def _describe_actor(spec: Spec, name: str) -> dict:
    cls = next((a for a in spec.actors if a.__name__ == name), None)
    if cls is None:
        return _not_found("actor", name, [a.__name__ for a in spec.actors])
    return {
        "kind": "actor",
        "name": name,
        "description": (cls.__doc__ or "").strip(),
        "actions": [a.id for a in spec.actions if a.by is cls],
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
        "handled_by": [a.id for a in spec.actions if cls in a.on],
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
        "entities": sorted({r.entity_cls.__name__ for r in _collect_field_refs(inv.expression)}),
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
        "by": action.by.__name__ if action.by is not None else None,
        "pre": [_describe(p) for p in action.pre],
        "effect": [_effect_str(e) for e in action.effect],
        "post": [_describe(p) for p in action.post],
        "emits": [_emit_str(e) for e in action.emits],
        "on": [e.__name__ for e in action.on if isinstance(e, type)],
        "requires": [r.id for r in action.requires],
        "required_by": [a.id for a in spec.actions
                        if any(r.id == action.id for r in a.requires)],
        "flows": [f.id for f in spec.flows
                  if any(s.id == action.id for s in f.steps)],
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
            {"from": _value_str(t.from_state), "to": [_value_str(s) for s in t.to_states]}
            for t in lc.transitions
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
        "steps": [s.id for s in flow.steps],
    }


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
    def _matches(ref: FieldDescriptor) -> bool:
        return ref.entity_cls.__name__ == entity_name and ref.field_name == field_name

    written_by = []
    for a in spec.actions:
        for w in _action_writes(a):
            if _matches(w.field):
                written_by.append({"action": a.id, "effect": _effect_str(w)})

    read_by = sorted({a.id for a in spec.actions
                      if any(_matches(r) for r in _action_refs(a))})
    invariants = [i.id for i in spec.invariants
                  if any(_matches(r) for r in _collect_field_refs(i.expression))]
    lifecycles = [lc.id for lc in spec.lifecycles
                  if isinstance(lc.field, FieldDescriptor) and _matches(lc.field)]

    event_bindings = []
    for a in spec.actions:
        for emitted in a.emits:
            if isinstance(emitted, type):
                continue
            for f, v in emitted.__dict__.items():
                if isinstance(v, FieldDescriptor) and _matches(v):
                    event_bindings.append(
                        {"action": a.id, "event": type(emitted).__name__, "payload_field": f})

    impacted_actions = sorted({w["action"] for w in written_by} | set(read_by))
    return {
        "kind": "field",
        "target": f"{entity_name}.{field_name}",
        "written_by": written_by,
        "read_by": read_by,
        "invariants": invariants,
        "lifecycles": lifecycles,
        "event_bindings": event_bindings,
        "scenarios": sorted({sc.id for sc in spec.scenarios
                             if sc.action.id in impacted_actions}),
    }


def _affects_entity(spec: Spec, name: str) -> dict:
    cls = next((e for e in list(spec.entities) + list(spec.events) if e.__name__ == name), None)
    described = (_describe_entity if cls in spec.entities else _describe_event)(spec, name)
    described["kind"] = "affects"
    return described


def _affects_action(spec: Spec, action_id: str) -> dict:
    action = next(a for a in spec.actions if a.id == action_id)
    emitted_classes = [(e if isinstance(e, type) else type(e)) for e in action.emits]
    downstream = sorted({a.id for a in spec.actions
                         if any(cls in a.on for cls in emitted_classes)})
    return {
        "kind": "action-impact",
        "target": action_id,
        "reads": sorted({_describe_operand(r) for r in _action_refs(action)}),
        "writes": [_effect_str(w) for w in _action_writes(action)],
        "emits": [_emit_str(e) for e in action.emits],
        "triggers_downstream": downstream,
        "required_by": [a.id for a in spec.actions
                        if any(r.id == action_id for r in a.requires)],
        "flows": [f.id for f in spec.flows if any(s.id == action_id for s in f.steps)],
        "scenarios": _scenarios_of(spec, action_id),
    }
