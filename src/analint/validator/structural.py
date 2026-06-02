from __future__ import annotations
from analint.models.entity import FieldDescriptor
from analint.models.root import Spec
from analint.models.predicate import (
    _Eq, _Ne, _Gt, _Gte, _Lt, _Lte,
    _And, _Or, _Not,
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

    # Duplicate id checks
    for kind, ids in [
        ("rule", [r.id for r in spec.rules]),
        ("use_case", [uc.id for uc in spec.use_cases]),
        ("scenario", [sc.id for sc in spec.scenarios]),
    ]:
        seen: set[str] = set()
        for id_ in ids:
            if id_ in seen:
                findings.append(err(f"{kind}:{id_}", f"duplicate id '{id_}'"))
            seen.add(id_)

    # Collect registered entity names
    spec_entity_names = {e.__name__ for e in spec.entities}
    rule_ids = {r.id for r in spec.rules}
    use_case_ids = {uc.id for uc in spec.use_cases}

    # StateMachines
    sm_ids: set[str] = set()
    for sm in spec.state_machines:
        if sm.id in sm_ids:
            findings.append(err(f"state_machine:{sm.id}", f"duplicate id '{sm.id}'"))
        sm_ids.add(sm.id)

        if not isinstance(sm.field, FieldDescriptor):
            findings.append(err(f"state_machine:{sm.id}", "field must be a FieldDescriptor (e.g. Order.status)"))
            continue

        if sm.entity_cls.__name__ not in spec_entity_names:
            findings.append(err(f"state_machine:{sm.id}",
                                f"entity '{sm.entity_cls.__name__}' not in spec.entities"))

        reachable = sm.reachable_states()
        for t in sm.transitions:
            for to_state in t.to_states:
                if to_state not in reachable and t.from_state == sm.initial:
                    pass  # always reachable from initial by definition


    # Rules: validate FieldDescriptor refs point to registered entities and known fields
    for rule in spec.rules:
        if rule.expression is not None:
            for ref_err in _check_pred_refs(rule.expression, spec.entities, f"rule:{rule.id}"):
                findings.append(ref_err)

    spec_actor_names = {a.__name__ for a in spec.actors}
    spec_event_names = {e.__name__ for e in spec.events}

    # Actors: all registered actors must subclass Actor
    for actor_cls in spec.actors:
        if not (isinstance(actor_cls, type) and issubclass(actor_cls, Actor)):
            findings.append(err(f"actor:{actor_cls}",
                                f"'{actor_cls}' does not subclass Actor"))

    # Events: all registered events must subclass Event
    for event_cls in spec.events:
        if not (isinstance(event_cls, type) and issubclass(event_cls, Event)):
            findings.append(err(f"event:{event_cls}",
                                f"'{event_cls}' does not subclass Event"))

    # Requires: build dependency graph, detect cycles
    uc_by_id = {uc.id: uc for uc in spec.use_cases}
    _check_requires_cycles(spec.use_cases, uc_by_id, findings, err)

    # Use cases: entities, rules, actor, emits, triggered_by must be registered in spec
    triggered_event_names: set[str] = set()
    for uc in spec.use_cases:
        for event_cls in uc.triggered_by:
            triggered_event_names.add(event_cls.__name__)

    for uc in spec.use_cases:
        for entity_cls in uc.entities:
            if entity_cls.__name__ not in spec_entity_names:
                findings.append(err(f"use_case:{uc.id}",
                                    f"entity '{entity_cls.__name__}' not in spec.entities"))
        for rule in uc.rules:
            if rule.id not in rule_ids:
                findings.append(err(f"use_case:{uc.id}",
                                    f"rule '{rule.id}' not in spec.rules"))

        if uc.actor is not None:
            if not (isinstance(uc.actor, type) and issubclass(uc.actor, Actor)):
                findings.append(err(f"use_case:{uc.id}",
                                    f"actor '{uc.actor}' does not subclass Actor"))
            elif uc.actor.__name__ not in spec_actor_names:
                findings.append(err(f"use_case:{uc.id}",
                                    f"actor '{uc.actor.__name__}' not in spec.actors"))

        for req_uc in uc.requires:
            if req_uc.id not in use_case_ids:
                findings.append(err(f"use_case:{uc.id}",
                                    f"required use_case '{req_uc.id}' not in spec.use_cases"))

        for event_cls in uc.emits:
            if event_cls.__name__ not in spec_event_names:
                findings.append(err(f"use_case:{uc.id}",
                                    f"emitted event '{event_cls.__name__}' not in spec.events"))
            elif event_cls.__name__ not in triggered_event_names:
                findings.append(warn(f"use_case:{uc.id}",
                                     f"event '{event_cls.__name__}' is emitted but never triggers a use_case"))

        for event_cls in uc.triggered_by:
            if event_cls.__name__ not in spec_event_names:
                findings.append(err(f"use_case:{uc.id}",
                                    f"triggered_by event '{event_cls.__name__}' not in spec.events"))

        if not any(sc.use_case.id == uc.id for sc in spec.scenarios):
            findings.append(warn(f"use_case:{uc.id}", "has no scenarios"))

    # Scenarios: use_case registered; given covers entity types needed by rules
    for sc in spec.scenarios:
        if sc.use_case.id not in use_case_ids:
            findings.append(err(f"scenario:{sc.id}",
                                f"use_case '{sc.use_case.id}' not in spec.use_cases"))
            continue

        given_types = {type(inst) for inst in sc.given}
        needed_types = _collect_ref_entity_types(sc.use_case.rules)
        for ent_cls in needed_types:
            if ent_cls not in given_types:
                findings.append(warn(f"scenario:{sc.id}",
                                     f"entity '{ent_cls.__name__}' referenced by rules but not in given"))

        # StateMachine reachability: given state must be reachable from initial
        for sm in spec.state_machines:
            if not isinstance(sm.field, FieldDescriptor):
                continue
            for inst in sc.given:
                if type(inst) is not sm.entity_cls:
                    continue
                given_state = getattr(inst, sm.field_name, None)
                if given_state is not None and given_state not in sm.reachable_states():
                    findings.append(warn(
                        f"scenario:{sc.id}",
                        f"{sm.entity_cls.__name__}.{sm.field_name}={given_state!r} "
                        f"is not reachable from initial state {sm.initial!r}",
                    ))

    # Flows: steps must be registered UCs; order consistent with requires
    flow_ids: set[str] = set()
    for flow in spec.flows:
        if flow.id in flow_ids:
            findings.append(err(f"flow:{flow.id}", f"duplicate id '{flow.id}'"))
        flow_ids.add(flow.id)

        for step in flow.steps:
            if step.id not in use_case_ids:
                findings.append(err(f"flow:{flow.id}",
                                    f"step '{step.id}' not in spec.use_cases"))

        # Verify requires order: if UC B requires A, A must appear before B in steps
        seen_steps: set[str] = set()
        for step in flow.steps:
            for req in step.requires:
                if req.id not in seen_steps:
                    findings.append(err(f"flow:{flow.id}",
                                        f"'{step.id}' requires '{req.id}' "
                                        f"but '{req.id}' does not appear before it in steps"))
            seen_steps.add(step.id)

    # Effects: field descriptors must point to registered entities
    for uc in spec.use_cases:
        for effect in uc.effects:
            if isinstance(effect, (Set, Subtract, Add)):
                if not isinstance(effect.field, FieldDescriptor):
                    findings.append(err(f"use_case:{uc.id}",
                                        "effect field must be a FieldDescriptor"))
                    continue
                cls = effect.field.entity_cls
                if cls.__name__ not in spec_entity_names:
                    findings.append(err(f"use_case:{uc.id}",
                                        f"effect targets entity '{cls.__name__}' not in spec.entities"))

    return findings


def _check_pred_refs(pred: object, spec_entities: list, loc: str) -> list[Finding]:
    findings: list[Finding] = []
    spec_entity_names = {e.__name__ for e in spec_entities}
    for ref in _collect_field_refs(pred):
        cls = ref.entity_cls
        if not hasattr(cls, "_own_fields"):
            findings.append(Finding(Severity.ERROR, loc,
                                    f"FieldDescriptor references non-Entity class '{cls.__name__}'"))
            continue
        if cls.__name__ not in spec_entity_names:
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


def _collect_field_refs(pred: object) -> list[FieldDescriptor]:
    refs: list[FieldDescriptor] = []
    if isinstance(pred, (_And, _Or)):
        for e in pred.exprs:
            refs.extend(_collect_field_refs(e))
    elif isinstance(pred, _Not):
        refs.extend(_collect_field_refs(pred.expr))
    elif isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        if isinstance(pred.left, FieldDescriptor):
            refs.append(pred.left)
        if isinstance(pred.right, FieldDescriptor):
            refs.append(pred.right)
    elif isinstance(pred, (_In, _IsNull, _IsNotNull)):
        if isinstance(pred.operand, FieldDescriptor):
            refs.append(pred.operand)
    return refs


def _collect_ref_entity_types(rules: list) -> set[type]:
    types: set[type] = set()
    for rule in rules:
        if rule.expression is not None:
            for ref in _collect_field_refs(rule.expression):
                types.add(ref.entity_cls)
    return types


def _check_requires_cycles(
    use_cases: list,
    uc_by_id: dict,
    findings: list[Finding],
    err_fn,
) -> None:
    """DFS cycle detection on the requires graph."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {uc.id: WHITE for uc in use_cases}

    def dfs(uc_id: str) -> bool:
        color[uc_id] = GRAY
        uc = uc_by_id.get(uc_id)
        if uc is None:
            color[uc_id] = BLACK
            return False
        for req in uc.requires:
            nid = req.id
            if nid not in color:
                color[nid] = WHITE
            if color[nid] == GRAY:
                findings.append(err_fn(
                    f"use_case:{uc_id}",
                    f"circular dependency detected involving '{nid}'",
                ))
                color[uc_id] = BLACK
                return True
            if color[nid] == WHITE:
                if dfs(nid):
                    color[uc_id] = BLACK
                    return True
        color[uc_id] = BLACK
        return False

    for uc in use_cases:
        if color[uc.id] == WHITE:
            dfs(uc.id)


def _describe_operand(op: object) -> str:
    if isinstance(op, FieldDescriptor):
        return f"{op.entity_cls.__name__}.{op.field_name}"
    if hasattr(op, "name") and hasattr(op, "value"):
        return f"{type(op).__name__}.{op.name}"
    return repr(op)


def _describe(pred: object) -> str:
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
    if isinstance(pred, _In):
        return f"{_describe_operand(pred.operand)} in {pred.values!r}"
    if isinstance(pred, _IsNull):
        return f"{_describe_operand(pred.operand)} is None"
    if isinstance(pred, _IsNotNull):
        return f"{_describe_operand(pred.operand)} is not None"
    return repr(pred)
