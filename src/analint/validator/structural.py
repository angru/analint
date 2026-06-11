from __future__ import annotations
from typing import Any

from analint.models.entity import FieldDescriptor
from analint.models.root import Spec
from analint.models.predicate import (
    Predicate,
    _Eq, _Ne, _Gt, _Gte, _Lt, _Lte,
    _And, _Or, _Not, _Implies,
    _In, _IsNull, _IsNotNull,
)
from analint.reporter.base import Finding, Severity
from analint.models.actor import Actor
from analint.models.event import Event
from analint.models.effect import Set, Subtract, Add


def validate_structural(spec: Spec) -> list[Finding]:
    findings: list[Finding] = []

    def err(loc: str, msg: str) -> Finding:
        return Finding(Severity.ERROR, loc, msg)

    def warn(loc: str, msg: str) -> Finding:
        return Finding(Severity.WARNING, loc, msg)

    # Missing and duplicate ids
    for kind, objs in [
        ("invariant", spec.invariants),
        ("action", spec.actions),
        ("scenario", spec.scenarios),
        ("lifecycle", spec.lifecycles),
        ("flow", spec.flows),
        ("query", spec.queries),
    ]:
        seen: set[str] = set()
        for obj in objs:
            if not obj.id:
                findings.append(err(f"{kind}:?",
                                    f"{kind} has no id — assign it to a module-level "
                                    f"variable or set id= explicitly"))
                continue
            if obj.id in seen:
                findings.append(err(f"{kind}:{obj.id}", f"duplicate id '{obj.id}'"))
            seen.add(obj.id)

    # Duplicate entity class names with different identities — almost always
    # the same file imported under two module names (use relative imports)
    for kind, classes in [("entity", spec.entities), ("actor", spec.actors), ("event", spec.events)]:
        by_name: dict[str, type] = {}
        for cls in classes:
            other = by_name.get(cls.__name__)
            if other is not None and other is not cls:
                findings.append(err(
                    f"{kind}:{cls.__name__}",
                    f"two different classes named '{cls.__name__}' are registered "
                    f"({other.__module__} and {cls.__module__}) — the same file is "
                    f"probably imported under two module names; use relative imports"))
            by_name[cls.__name__] = cls

    spec_entity_names = {e.__name__ for e in spec.entities}
    spec_actor_names = {a.__name__ for a in spec.actors}
    spec_event_names = {e.__name__ for e in spec.events}
    action_ids = {a.id for a in spec.actions}

    # Actors / Events: registered classes must subclass the right base
    for actor_cls in spec.actors:
        if not (isinstance(actor_cls, type) and issubclass(actor_cls, Actor)):
            findings.append(err(f"actor:{actor_cls}", f"'{actor_cls}' does not subclass Actor"))
    for event_cls in spec.events:
        if not (isinstance(event_cls, type) and issubclass(event_cls, Event)):
            findings.append(err(f"event:{event_cls}", f"'{event_cls}' does not subclass Event"))

    # Invariants: expressions reference registered entities and existing fields
    for inv in spec.invariants:
        findings.extend(_check_pred_refs(inv.expression, spec.entities, spec.events,
                                         f"invariant:{inv.id}"))

    # Requires cycles
    action_by_id = {a.id: a for a in spec.actions}
    _check_requires_cycles(spec.actions, action_by_id, findings, err)

    handled_event_names: set[str] = set()
    for action in spec.actions:
        for event_cls in action.on:
            if isinstance(event_cls, type):
                handled_event_names.add(event_cls.__name__)

    for action in spec.actions:
        loc = f"action:{action.id}"

        for pred in list(action.pre) + list(action.post):
            findings.extend(_check_pred_refs(pred, spec.entities, spec.events, loc))

        if action.by is not None:
            if not (isinstance(action.by, type) and issubclass(action.by, Actor)):
                findings.append(err(loc, f"by='{action.by}' does not subclass Actor"))
            elif action.by.__name__ not in spec_actor_names:
                findings.append(err(loc, f"actor '{action.by.__name__}' not in spec.actors"))

        for req in action.requires:
            if req.id not in action_ids:
                findings.append(err(loc, f"required action '{req.id}' not in spec.actions"))

        # emits: classes or payload templates (Event instances)
        for emitted in action.emits:
            event_cls = emitted if isinstance(emitted, type) else type(emitted)
            if not issubclass(event_cls, Event):
                findings.append(err(loc, f"emits entry '{emitted!r}' is not an Event"))
                continue
            if event_cls.__name__ not in spec_event_names:
                findings.append(err(loc, f"emitted event '{event_cls.__name__}' not in spec.events"))
            elif event_cls.__name__ not in handled_event_names:
                findings.append(warn(loc, f"event '{event_cls.__name__}' is emitted "
                                          f"but never triggers an action"))
            if not isinstance(emitted, type):
                findings.extend(_check_event_template(emitted, spec.entities, loc))

        for event_cls in action.on:
            if not (isinstance(event_cls, type) and issubclass(event_cls, Event)):
                findings.append(err(loc, f"on entry '{event_cls!r}' must be an Event class"))
            elif event_cls.__name__ not in spec_event_names:
                findings.append(err(loc, f"on event '{event_cls.__name__}' not in spec.events"))

        # effects: registered targets, no two effects on the same field
        effect_targets: set[tuple[type, str]] = set()
        for effect in action.effect:
            if not isinstance(effect, (Set, Subtract, Add)):
                findings.append(err(loc, f"effect entry '{effect!r}' is not Set/Add/Subtract"))
                continue
            if not isinstance(effect.field, FieldDescriptor):
                findings.append(err(loc, "effect field must be a FieldDescriptor"))
                continue
            cls = effect.field.entity_cls
            if cls.__name__ not in spec_entity_names:
                findings.append(err(loc, f"effect targets entity '{cls.__name__}' "
                                         f"not in spec.entities"))
            target = (cls, effect.field.field_name)
            if target in effect_targets:
                findings.append(err(loc, f"two effects target '{cls.__name__}."
                                         f"{effect.field.field_name}' — effects are "
                                         f"simultaneous, a field can change only once"))
            effect_targets.add(target)

        if not any(sc.action.id == action.id for sc in spec.scenarios):
            findings.append(warn(loc, "has no scenarios"))

    # Lifecycles
    for lc in spec.lifecycles:
        loc = f"lifecycle:{lc.id or '?'}"
        if lc._entity_cls is None:
            findings.append(err(loc, "lifecycle is not attached to an entity field — "
                                     "declare it as the field's default value"))
            continue
        if lc.entity_cls.__name__ not in spec_entity_names:
            findings.append(err(loc, f"entity '{lc.entity_cls.__name__}' not in spec.entities"))
        for t in lc.transitions:
            if t.from_state in lc.terminal:
                findings.append(err(loc, f"transition out of terminal state {t.from_state!r}"))

    # Scenarios
    for sc in spec.scenarios:
        loc = f"scenario:{sc.id}"
        if sc.action.id not in action_ids:
            findings.append(err(loc, f"action '{sc.action.id}' not in spec.actions"))
            continue

        given_types = {type(inst) for inst in sc.given}
        needed = _needed_types(sc.action)
        for cls in needed:
            if cls not in given_types:
                findings.append(warn(loc, f"'{cls.__name__}' referenced by the action "
                                          f"but not in given"))

        for lc in spec.lifecycles:
            if lc._entity_cls is None:
                continue
            for inst in sc.given:
                if type(inst) is not lc.entity_cls:
                    continue
                state = getattr(inst, lc.field_name, None)
                if state is not None and state not in lc.reachable_states():
                    findings.append(warn(
                        loc,
                        f"{lc.entity_cls.__name__}.{lc.field_name}={state!r} "
                        f"is not reachable from initial state {lc.initial!r}"))

    # Queries: predicates reference registered entities
    for query in spec.queries:
        pred = getattr(query, "predicate", None) or getattr(query, "goal", None)
        if pred is not None:
            findings.extend(_check_pred_refs(pred, spec.entities, spec.events,
                                             f"query:{query.id}"))

    # Flows: steps registered; requires order respected
    for flow in spec.flows:
        loc = f"flow:{flow.id}"
        for step in flow.steps:
            if step.id not in action_ids:
                findings.append(err(loc, f"step '{step.id}' not in spec.actions"))
        seen_steps: set[str] = set()
        for step in flow.steps:
            for req in step.requires:
                if req.id not in seen_steps:
                    findings.append(err(loc, f"'{step.id}' requires '{req.id}' but "
                                             f"'{req.id}' does not appear before it in steps"))
            seen_steps.add(step.id)

    return findings


def _needed_types(action) -> set[type]:
    """Entity/Event types an action's predicates and effects reference."""
    types: set[type] = set()
    for pred in list(action.pre) + list(action.post):
        for ref in _collect_field_refs(pred):
            types.add(ref.entity_cls)
    for effect in action.effect:
        if isinstance(effect, (Set, Subtract, Add)) and isinstance(effect.field, FieldDescriptor):
            types.add(effect.field.entity_cls)
    return types


def _check_event_template(template, spec_entities: list, loc: str) -> list[Finding]:
    """Validate a payload template: bound FieldDescriptors must point to
    registered entities; annotations are compared when both sides have them."""
    findings: list[Finding] = []
    spec_entity_names = {e.__name__ for e in spec_entities}
    event_cls = type(template)
    event_ann = getattr(event_cls, "__annotations__", {})
    for field_name in getattr(event_cls, "_own_fields", {}):
        value = template.__dict__.get(field_name)
        if not isinstance(value, FieldDescriptor):
            continue
        src_cls = value.entity_cls
        if src_cls.__name__ not in spec_entity_names:
            findings.append(Finding(
                Severity.ERROR, loc,
                f"payload {event_cls.__name__}.{field_name} is bound to "
                f"'{src_cls.__name__}.{value.field_name}' but '{src_cls.__name__}' "
                f"is not in spec.entities"))
            continue
        src_ann = getattr(src_cls, "__annotations__", {}).get(value.field_name)
        dst_ann = event_ann.get(field_name)
        if src_ann is not None and dst_ann is not None and str(src_ann) != str(dst_ann):
            findings.append(Finding(
                Severity.WARNING, loc,
                f"payload {event_cls.__name__}.{field_name}: {dst_ann} is bound to "
                f"{src_cls.__name__}.{value.field_name}: {src_ann} — types differ"))
    return findings


def _check_pred_refs(
    pred: Predicate,
    spec_entities: list[type],
    spec_events: list[type],
    loc: str,
) -> list[Finding]:
    findings: list[Finding] = []
    known_names = {e.__name__ for e in spec_entities} | {e.__name__ for e in spec_events}
    for ref in _collect_field_refs(pred):
        cls = ref.entity_cls
        if not hasattr(cls, "_own_fields"):
            findings.append(Finding(Severity.ERROR, loc,
                                    f"FieldDescriptor references non-Entity class '{cls.__name__}'"))
            continue
        if cls.__name__ not in known_names:
            findings.append(Finding(Severity.ERROR, loc,
                                    f"entity '{cls.__name__}' not in spec.entities"))
            continue
        all_fields: dict = {}
        for klass in reversed(cls.__mro__):
            all_fields.update(getattr(klass, "_own_fields", {}))
        if ref.field_name not in all_fields:
            findings.append(Finding(Severity.ERROR, loc,
                                    f"field '{cls.__name__}.{ref.field_name}' does not exist"))
    return findings


def _collect_field_refs(pred: Predicate) -> list[FieldDescriptor]:
    refs: list[FieldDescriptor] = []
    if isinstance(pred, (_And, _Or)):
        for e in pred.exprs:
            refs.extend(_collect_field_refs(e))
    elif isinstance(pred, _Not):
        refs.extend(_collect_field_refs(pred.expr))
    elif isinstance(pred, _Implies):
        refs.extend(_collect_field_refs(pred.left))
        refs.extend(_collect_field_refs(pred.right))
    elif isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        if isinstance(pred.left, FieldDescriptor):
            refs.append(pred.left)
        if isinstance(pred.right, FieldDescriptor):
            refs.append(pred.right)
    elif isinstance(pred, (_In, _IsNull, _IsNotNull)):
        if isinstance(pred.operand, FieldDescriptor):
            refs.append(pred.operand)
    return refs


def _check_requires_cycles(
    actions: list,
    action_by_id: dict,
    findings: list[Finding],
    err_fn,
) -> None:
    """DFS cycle detection on the requires graph."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {a.id: WHITE for a in actions}

    def dfs(action_id: str) -> bool:
        color[action_id] = GRAY
        action = action_by_id.get(action_id)
        if action is None:
            color[action_id] = BLACK
            return False
        for req in action.requires:
            nid = req.id
            if nid not in color:
                color[nid] = WHITE
            if color[nid] == GRAY:
                findings.append(err_fn(
                    f"action:{action_id}",
                    f"circular dependency detected involving '{nid}'",
                ))
                color[action_id] = BLACK
                return True
            if color[nid] == WHITE:
                if dfs(nid):
                    color[action_id] = BLACK
                    return True
        color[action_id] = BLACK
        return False

    for action in actions:
        if color[action.id] == WHITE:
            dfs(action.id)


def _describe_operand(op: Any) -> str:
    if isinstance(op, FieldDescriptor):
        return f"{op.entity_cls.__name__}.{op.field_name}"
    if hasattr(op, "name") and hasattr(op, "value"):
        return f"{type(op).__name__}.{op.name}"
    return repr(op)


def _describe(pred: Predicate) -> str:
    if isinstance(pred, _Eq):
        return f"{_describe_operand(pred.left)} == {_describe_operand(pred.right)}"
    if isinstance(pred, _Ne):
        return f"{_describe_operand(pred.left)} != {_describe_operand(pred.right)}"
    if isinstance(pred, _Gt):
        return f"{_describe_operand(pred.left)} > {_describe_operand(pred.right)}"
    if isinstance(pred, _Gte):
        return f"{_describe_operand(pred.left)} >= {_describe_operand(pred.right)}"
    if isinstance(pred, _Lt):
        return f"{_describe_operand(pred.left)} < {_describe_operand(pred.right)}"
    if isinstance(pred, _Lte):
        return f"{_describe_operand(pred.left)} <= {_describe_operand(pred.right)}"
    if isinstance(pred, _And):
        inner = ", ".join(_describe(e) for e in pred.exprs)
        return f"AND({inner})"
    if isinstance(pred, _Or):
        inner = ", ".join(_describe(e) for e in pred.exprs)
        return f"OR({inner})"
    if isinstance(pred, _Not):
        return f"NOT({_describe(pred.expr)})"
    if isinstance(pred, _Implies):
        return f"IF {_describe(pred.left)} THEN {_describe(pred.right)}"
    if isinstance(pred, _In):
        return f"{_describe_operand(pred.operand)} in {pred.values!r}"
    if isinstance(pred, _IsNull):
        return f"{_describe_operand(pred.operand)} is None"
    if isinstance(pred, _IsNotNull):
        return f"{_describe_operand(pred.operand)} is not None"
    return repr(pred)
