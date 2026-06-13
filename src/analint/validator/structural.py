from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from analint.models.action import Action
from analint.models.actor import Actor
from analint.models.effect import Add, Create, Delete, Set, Subtract
from analint.models.entity import FieldDescriptor, all_fields
from analint.models.event import Event
from analint.models.expr import Expr, expr_op
from analint.models.flow import Assert, Emitted
from analint.models.predicate import (
    Predicate,
    _And,
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
from analint.models.scope import (
    InstanceField,
    InstanceRef,
    context_key_label,
    field_context_key,
    instance_context_key,
    is_field_ref,
)
from analint.reporter.base import Finding, Severity


def validate_structural(spec: Spec) -> list[Finding]:
    findings: list[Finding] = []

    def err(loc: str, msg: str) -> Finding:
        return Finding(Severity.ERROR, loc, msg)

    def warn(loc: str, msg: str) -> Finding:
        return Finding(Severity.WARNING, loc, msg)

    seen_contracts: set[str] = set()
    for contract in spec.imports:
        loc = f"contract:{contract.id or '?'}"
        if not contract.id:
            findings.append(err(loc, "contract has no id"))
        elif contract.id in seen_contracts:
            findings.append(err(loc, f"duplicate imported contract id '{contract.id}'"))
        seen_contracts.add(contract.id)

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
                findings.append(
                    err(
                        f"{kind}:?",
                        f"{kind} has no id — assign it to a module-level "
                        f"variable or set id= explicitly",
                    )
                )
                continue
            if obj.id in seen:
                findings.append(err(f"{kind}:{obj.id}", f"duplicate id '{obj.id}'"))
            seen.add(obj.id)

    # Duplicate entity class names with different identities — almost always
    # the same file imported under two module names (use relative imports)
    for kind, classes in [
        ("entity", spec.entities),
        ("actor", spec.actors),
        ("event", spec.events),
    ]:
        by_name: dict[str, type] = {}
        for cls in classes:
            other = by_name.get(cls.__name__)
            if other is not None and other is not cls:
                findings.append(
                    err(
                        f"{kind}:{cls.__name__}",
                        f"two different classes named '{cls.__name__}' are registered "
                        f"({other.__module__} and {cls.__module__}) — the same file is "
                        f"probably imported under two module names; use relative imports",
                    )
                )
            by_name[cls.__name__] = cls

    spec_entity_names = {e.__name__ for e in spec.entities}
    spec_actor_names = {a.__name__ for a in spec.actors}
    spec_event_names = {e.__name__ for e in spec.events}
    action_ids = {a.id for a in spec.actions}

    scoped_entities: dict[type, Any] = {}
    for scope in spec.scopes:
        loc = f"scope:{scope.id or scope.entity_cls.__name__}"
        if scope.entity_cls not in spec.entities:
            findings.append(err(loc, f"entity '{scope.entity_cls.__name__}' not in spec.entities"))
        if scope.entity_cls in scoped_entities:
            findings.append(
                err(loc, f"entity '{scope.entity_cls.__name__}' has more than one Scope")
            )
        scoped_entities[scope.entity_cls] = scope

    # Actors / Events: registered classes must subclass the right base
    for actor_cls in spec.actors:
        if not (isinstance(actor_cls, type) and issubclass(actor_cls, Actor)):
            findings.append(err(f"actor:{actor_cls}", f"'{actor_cls}' does not subclass Actor"))
    for event_cls in spec.events:
        if not (isinstance(event_cls, type) and issubclass(event_cls, Event)):
            findings.append(err(f"event:{event_cls}", f"'{event_cls}' does not subclass Event"))

    # Invariants: expressions reference registered entities and existing fields
    for inv in spec.invariants:
        findings.extend(
            _check_pred_refs(
                inv.expression,
                spec.entities,
                spec.events,
                f"invariant:{inv.id}",
                spec.scopes,
            )
        )
        findings.extend(
            _check_scoped_refs(
                _collect_field_refs(inv.expression), scoped_entities, f"invariant:{inv.id}"
            )
        )

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

        if action.where and not action.params:
            findings.append(
                err(
                    loc,
                    "where= only filters parameterized action bindings; "
                    "use pre= for state-dependent conditions",
                )
            )

        for pred in list(action.pre) + list(action.post):
            findings.extend(_check_pred_refs(pred, spec.entities, spec.events, loc, spec.scopes))
            findings.extend(_check_scoped_refs(_collect_field_refs(pred), scoped_entities, loc))

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
                findings.append(
                    err(loc, f"emitted event '{event_cls.__name__}' not in spec.events")
                )
            elif event_cls.__name__ not in handled_event_names:
                findings.append(
                    warn(
                        loc, f"event '{event_cls.__name__}' is emitted but never triggers an action"
                    )
                )
            if not isinstance(emitted, type):
                findings.extend(_check_event_template(emitted, spec.entities, loc))
                findings.extend(
                    _check_scoped_refs(
                        [value for value in emitted.__dict__.values() if is_field_ref(value)],
                        scoped_entities,
                        loc,
                    )
                )

        for event_cls in action.on:
            if not (isinstance(event_cls, type) and issubclass(event_cls, Event)):
                findings.append(err(loc, f"on entry '{event_cls!r}' must be an Event class"))
            elif event_cls.__name__ not in spec_event_names:
                findings.append(err(loc, f"on event '{event_cls.__name__}' not in spec.events"))

        # effects: registered targets, no two facts about the same field or slot
        effect_targets: set[tuple[Any, str]] = set()
        presence_targets: set[Any] = set()  # slots a Create/Delete makes (dis)appear
        field_slots: set[Any] = set()  # slots whose fields a Set/Add/Subtract writes
        for effect in action.effect:
            if isinstance(effect, (Create, Delete)):
                target = effect.target
                if not isinstance(target, InstanceRef):
                    findings.append(
                        err(
                            loc,
                            f"{type(effect).__name__} target must be an InstanceRef from a "
                            f"Scope, got {target!r}",
                        )
                    )
                    continue
                if scoped_entities.get(target.entity_cls) is not target.scope:
                    findings.append(
                        err(loc, f"{target!r} belongs to a Scope not registered in spec.scopes")
                    )
                if isinstance(effect, Create):
                    known = all_fields(target.entity_cls)
                    for name in effect.fields:
                        if name not in known:
                            findings.append(
                                err(
                                    loc,
                                    f"Create({target!r}) sets unknown field "
                                    f"'{name}' on {target.entity_cls.__name__}",
                                )
                            )
                if target in presence_targets:
                    findings.append(
                        err(
                            loc,
                            f"two effects change the presence of {target!r} — effects are "
                            f"simultaneous, a slot can appear or disappear only once",
                        )
                    )
                presence_targets.add(target)
                continue
            if not isinstance(effect, (Set, Subtract, Add)):
                findings.append(
                    err(loc, f"effect entry '{effect!r}' is not Set/Add/Subtract/Create/Delete")
                )
                continue
            if not is_field_ref(effect.field):
                findings.append(err(loc, "effect field must be a field reference"))
                continue
            cls = effect.field.entity_cls
            if cls.__name__ not in spec_entity_names:
                findings.append(
                    err(loc, f"effect targets entity '{cls.__name__}' not in spec.entities")
                )
            findings.extend(_check_scoped_refs([effect.field], scoped_entities, loc))
            rhs = effect.value if isinstance(effect, Set) else effect.amount
            findings.extend(_check_scoped_refs(_operand_refs(rhs), scoped_entities, loc))
            field_slots.add(field_context_key(effect.field))
            target = (field_context_key(effect.field), effect.field.field_name)
            if target in effect_targets:
                findings.append(
                    err(
                        loc,
                        f"two effects target '{cls.__name__}."
                        f"{effect.field.field_name}' — effects are "
                        f"simultaneous, a field can change only once",
                    )
                )
            effect_targets.add(target)

        for slot in sorted(presence_targets & field_slots, key=context_key_label):
            findings.append(
                err(
                    loc,
                    f"{slot!r} is both created/deleted and modified by Set/Add/Subtract in the "
                    f"same action — these next-state facts conflict",
                )
            )

    # Scenario coverage is per family: one example for any binding of a
    # parameterized action covers the whole declaration.
    covered_families = {sc.action.family or sc.action.id for sc in spec.scenarios}
    warned_families: set[str] = set()
    for action in spec.actions:
        fam = action.family or action.id
        if fam in covered_families or fam in warned_families:
            continue
        warned_families.add(fam)
        findings.append(warn(f"action:{fam}", "has no scenarios"))

    # Lifecycles
    for lc in spec.lifecycles:
        loc = f"lifecycle:{lc.id or '?'}"
        if lc._entity_cls is None:
            findings.append(
                err(
                    loc,
                    "lifecycle is not attached to an entity field — "
                    "declare it as the field's default value",
                )
            )
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

        given_keys = {instance_context_key(inst) for inst in sc.given}
        for inst in sc.given:
            key = instance_context_key(inst)
            scope = scoped_entities.get(type(inst))
            if scope is not None and not isinstance(key, InstanceRef):
                findings.append(
                    err(
                        loc,
                        f"{type(inst).__name__} has Scope '{scope.id}' — create the "
                        f"snapshot through a registered InstanceRef",
                    )
                )
            elif isinstance(key, InstanceRef) and scoped_entities.get(type(inst)) is not key.scope:
                findings.append(
                    err(loc, f"{key!r} belongs to a Scope not registered in spec.scopes")
                )
        needed = _needed_keys(sc.action)
        for key in needed:
            if key not in given_keys:
                label = repr(key) if isinstance(key, InstanceRef) else key.__name__
                findings.append(warn(loc, f"'{label}' referenced by the action but not in given"))

        # then entries: only Assert/Emitted are checks — anything else would
        # be silently ignored at run time, which is a false-green path
        for assertion in sc.then:
            if isinstance(assertion, Assert):
                findings.extend(
                    _check_pred_refs(
                        assertion.predicate,
                        spec.entities,
                        spec.events,
                        loc,
                        spec.scopes,
                    )
                )
                findings.extend(
                    _check_scoped_refs(
                        _collect_field_refs(assertion.predicate), scoped_entities, loc
                    )
                )
            elif isinstance(assertion, Emitted):
                if not (
                    isinstance(assertion.event_cls, type) and issubclass(assertion.event_cls, Event)
                ):
                    findings.append(
                        err(loc, f"Emitted(...) needs an Event class, got {assertion.event_cls!r}")
                    )
            else:
                findings.append(
                    err(loc, f"then entry '{assertion!r}' must be Assert(...) or Emitted(...)")
                )

        for lc in spec.lifecycles:
            if lc._entity_cls is None:
                continue
            for inst in sc.given:
                if type(inst) is not lc.entity_cls:
                    continue
                state = getattr(inst, lc.field_name, None)
                if state is not None and state not in lc.reachable_states():
                    findings.append(
                        warn(
                            loc,
                            f"{lc.entity_cls.__name__}.{lc.field_name}={state!r} "
                            f"is not reachable from initial state {lc.initial!r}",
                        )
                    )

    # Queries: predicates reference registered entities
    for query in spec.queries:
        loc = f"query:{query.id}"
        initial_sources = bool(query.given) + bool(query.given_any) + (query.initial is not None)
        if initial_sources > 1:
            findings.append(
                err(
                    loc,
                    "use exactly one of given=, given_any=, or initial=, not both/multiple",
                )
            )

        if query.initial is not None:
            initial_refs: list[FieldDescriptor | InstanceField] = []
            initial_markers: set[tuple[Any, str]] = set()
            for item in query.initial.vary:
                if isinstance(item, BoundField):
                    if item.variable.scope not in spec.scopes:
                        findings.append(_unregistered_bound_scope(item.variable, loc))
                        continue
                    initial_refs.extend(
                        getattr(ref, item.field_name) for ref in item.variable.scope
                    )
                elif is_field_ref(item):
                    initial_refs.append(item)
                else:
                    findings.append(
                        err(
                            loc,
                            f"Initial vary entry '{item!r}' is not a field "
                            f"reference or Bound field",
                        )
                    )
            for ref in initial_refs:
                marker = (field_context_key(ref), ref.field_name)
                if marker in initial_markers:
                    findings.append(
                        err(
                            loc,
                            f"Initial varies {context_key_label(marker[0])}.{marker[1]} twice",
                        )
                    )
                initial_markers.add(marker)
                if ref.entity_cls not in spec.entities:
                    findings.append(
                        err(
                            loc,
                            f"Initial varies entity '{ref.entity_cls.__name__}' "
                            f"not in spec.entities",
                        )
                    )
            findings.extend(_check_scoped_refs(initial_refs, scoped_entities, loc))
            for pred in query.initial.where:
                findings.extend(
                    _check_pred_refs(pred, spec.entities, spec.events, loc, spec.scopes)
                )
                findings.extend(_check_scoped_refs(_collect_field_refs(pred), scoped_entities, loc))

        pred = getattr(query, "predicate", None) or getattr(query, "goal", None)
        if pred is not None:
            findings.extend(
                _check_pred_refs(
                    pred,
                    spec.entities,
                    spec.events,
                    loc,
                    spec.scopes,
                )
            )
            findings.extend(_check_scoped_refs(_collect_field_refs(pred), scoped_entities, loc))

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
                    findings.append(
                        err(
                            loc,
                            f"'{step.id}' requires '{req.id}' but "
                            f"'{req.id}' does not appear before it in steps",
                        )
                    )
            seen_steps.add(step.id)

    return findings


def _needed_keys(action: Action) -> set[Any]:
    """Entity/Event context keys an action's predicates and effects reference."""
    keys: set[Any] = set()
    for pred in list(action.pre) + list(action.post):
        for ref in _required_field_refs(pred):
            keys.add(field_context_key(ref))
    for effect in action.effect:
        if isinstance(effect, (Set, Subtract, Add)):
            if is_field_ref(effect.field):
                keys.add(field_context_key(effect.field))
            rhs = effect.value if isinstance(effect, Set) else effect.amount
            keys.update(field_context_key(ref) for ref in _required_operand_refs(rhs))
        elif isinstance(effect, (Create, Delete)) and isinstance(effect.target, InstanceRef):
            keys.add(effect.target)
    return keys


def _required_field_refs(
    pred: Predicate,
    bound: frozenset[Bound] = frozenset(),
) -> list[FieldDescriptor | InstanceField]:
    refs: list[FieldDescriptor | InstanceField] = []
    if isinstance(pred, (_And, _Or)):
        for expr in pred.exprs:
            refs.extend(_required_field_refs(expr, bound))
    elif isinstance(pred, _Not):
        refs.extend(_required_field_refs(pred.expr, bound))
    elif isinstance(pred, _Implies):
        refs.extend(_required_field_refs(pred.left, bound))
        refs.extend(_required_field_refs(pred.right, bound))
    elif isinstance(pred, (_ForAll, _Exists)):
        refs.extend(_required_field_refs(pred.predicate, bound | {pred.variable}))
    elif isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        refs.extend(_required_operand_refs(pred.left, bound))
        refs.extend(_required_operand_refs(pred.right, bound))
    elif isinstance(pred, _In):
        refs.extend(_required_operand_refs(pred.operand, bound))
        for value in pred.values:
            refs.extend(_required_operand_refs(value, bound))
    elif isinstance(pred, (_IsNull, _IsNotNull)):
        refs.extend(_required_operand_refs(pred.operand, bound))
    return refs


def _required_operand_refs(
    operand: Any,
    bound: frozenset[Bound] = frozenset(),
) -> list[FieldDescriptor | InstanceField]:
    if is_field_ref(operand):
        return [operand]
    if isinstance(operand, BoundField):
        return []
    if isinstance(operand, _Count):
        return _required_field_refs(operand.predicate, bound | {operand.variable})
    if isinstance(operand, (_Sum, _Min, _Max)):
        return _required_operand_refs(operand.operand, bound | {operand.variable})
    if isinstance(operand, Expr):
        return _required_operand_refs(operand.left, bound) + _required_operand_refs(  # type: ignore[attr-defined]
            operand.right,
            bound,  # type: ignore[attr-defined]
        )
    return []


def _check_scoped_refs(
    refs: Sequence[FieldDescriptor | InstanceField],
    scoped_entities: dict[type, Any],
    loc: str,
) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[type, str]] = set()
    for ref in refs:
        if isinstance(ref, InstanceField):
            if scoped_entities.get(ref.entity_cls) is not ref.instance.scope:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        loc,
                        f"{ref!r} belongs to a Scope not registered in spec.scopes",
                    )
                )
            continue
        if ref.entity_cls not in scoped_entities:
            continue
        marker = (ref.entity_cls, ref.field_name)
        if marker in seen:
            continue
        seen.add(marker)
        scope = scoped_entities[ref.entity_cls]
        findings.append(
            Finding(
                Severity.ERROR,
                loc,
                f"'{ref.entity_cls.__name__}.{ref.field_name}' is ambiguous because "
                f"{ref.entity_cls.__name__} has Scope '{scope.id or scope.entity_cls.__name__}' — "
                f"address an instance through the Scope or an instance Param",
            )
        )
    return findings


def _check_event_template(
    template: Event, spec_entities: Sequence[type], loc: str
) -> list[Finding]:
    """Validate a payload template: bound FieldDescriptors must point to
    registered entities; annotations are compared when both sides have them."""
    findings: list[Finding] = []
    spec_entity_names = {e.__name__ for e in spec_entities}
    event_cls = type(template)
    event_ann = getattr(event_cls, "__annotations__", {})
    for field_name in getattr(event_cls, "_own_fields", {}):
        value = template.__dict__.get(field_name)
        if not is_field_ref(value):
            continue
        src_cls = value.entity_cls
        if src_cls.__name__ not in spec_entity_names:
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"payload {event_cls.__name__}.{field_name} is bound to "
                    f"'{src_cls.__name__}.{value.field_name}' but '{src_cls.__name__}' "
                    f"is not in spec.entities",
                )
            )
            continue
        src_ann = getattr(src_cls, "__annotations__", {}).get(value.field_name)
        dst_ann = event_ann.get(field_name)
        if src_ann is not None and dst_ann is not None and str(src_ann) != str(dst_ann):
            findings.append(
                Finding(
                    Severity.WARNING,
                    loc,
                    f"payload {event_cls.__name__}.{field_name}: {dst_ann} is bound to "
                    f"{src_cls.__name__}.{value.field_name}: {src_ann} — types differ",
                )
            )
    return findings


def _check_pred_nodes(
    pred: Any,
    loc: str,
    bound: frozenset[Bound] = frozenset(),
) -> list[Finding]:
    """Every node of a predicate tree must be a known analint node.

    A foreign object would otherwise reach the evaluator and raise (or, worse,
    be silently skipped by walkers) — a verifier rejects it up front.
    """
    findings: list[Finding] = []
    if not isinstance(pred, Predicate):
        return [
            Finding(
                Severity.ERROR,
                loc,
                f"'{pred!r}' is not a predicate — build conditions from entity "
                f"field comparisons and And/Or/Not/Implies/In combinators",
            )
        ]
    if isinstance(pred, (_And, _Or)):
        for e in pred.exprs:
            findings.extend(_check_pred_nodes(e, loc, bound))
    elif isinstance(pred, _Not):
        findings.extend(_check_pred_nodes(pred.expr, loc, bound))
    elif isinstance(pred, _Implies):
        findings.extend(_check_pred_nodes(pred.left, loc, bound))
        findings.extend(_check_pred_nodes(pred.right, loc, bound))
    elif isinstance(pred, (_ForAll, _Exists)):
        if not isinstance(pred.variable, Bound):
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"{type(pred).__name__} variable must be Bound(...), got {pred.variable!r}",
                )
            )
        else:
            findings.extend(_check_pred_nodes(pred.predicate, loc, bound | {pred.variable}))
    elif isinstance(pred, _Present):
        if isinstance(pred.target, Bound):
            if pred.target not in bound:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        loc,
                        f"Present({pred.target.name}) uses Bound '{pred.target.name}' "
                        f"outside a quantifier",
                    )
                )
        elif not isinstance(pred.target, InstanceRef):
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"Present target must resolve to an InstanceRef, got {pred.target!r}",
                )
            )
    elif isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        findings.extend(_check_operand_nodes(pred.left, bound, loc))
        findings.extend(_check_operand_nodes(pred.right, bound, loc))
    elif isinstance(pred, _In):
        findings.extend(_check_operand_nodes(pred.operand, bound, loc))
        for value in pred.values:
            findings.extend(_check_operand_nodes(value, bound, loc))
    elif isinstance(pred, (_IsNull, _IsNotNull)):
        findings.extend(_check_operand_nodes(pred.operand, bound, loc))
    return findings


def _check_pred_refs(
    pred: Predicate,
    spec_entities: Sequence[type],
    spec_events: Sequence[type],
    loc: str,
    spec_scopes: Sequence[Any] = (),
) -> list[Finding]:
    findings = _check_pred_nodes(pred, loc)
    if findings:
        return findings
    findings.extend(_check_quantifier_scopes(pred, spec_scopes, loc))
    known_names = {e.__name__ for e in spec_entities} | {e.__name__ for e in spec_events}
    for ref in _collect_field_refs(pred):
        cls = ref.entity_cls
        if not hasattr(cls, "_own_fields"):
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"FieldDescriptor references non-Entity class '{cls.__name__}'",
                )
            )
            continue
        if cls.__name__ not in known_names:
            findings.append(
                Finding(Severity.ERROR, loc, f"entity '{cls.__name__}' not in spec.entities")
            )
            continue
        all_fields: dict = {}
        for klass in reversed(cls.__mro__):
            all_fields.update(getattr(klass, "_own_fields", {}))
        if ref.field_name not in all_fields:
            findings.append(
                Finding(
                    Severity.ERROR, loc, f"field '{cls.__name__}.{ref.field_name}' does not exist"
                )
            )
    return findings


def _check_operand_nodes(
    operand: Any,
    bound: frozenset[Bound],
    loc: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if isinstance(operand, BoundField):
        if operand.variable not in bound:
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"'{operand!r}' uses Bound '{operand.variable.name}' "
                    f"outside a quantifier or aggregate",
                )
            )
    elif isinstance(operand, _Count):
        if not isinstance(operand.variable, Bound):
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"_Count variable must be Bound(...), got {operand.variable!r}",
                )
            )
        else:
            findings.extend(_check_pred_nodes(operand.predicate, loc, bound | {operand.variable}))
    elif isinstance(operand, (_Sum, _Min, _Max)):
        if not isinstance(operand.variable, Bound):
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"{type(operand).__name__} variable must be Bound(...), "
                    f"got {operand.variable!r}",
                )
            )
        else:
            findings.extend(_check_operand_nodes(operand.operand, bound | {operand.variable}, loc))
    elif isinstance(operand, Expr):
        findings.extend(_check_operand_nodes(operand.left, bound, loc))  # type: ignore[attr-defined]
        findings.extend(_check_operand_nodes(operand.right, bound, loc))  # type: ignore[attr-defined]
    return findings


def _check_quantifier_scopes(
    pred: Predicate,
    spec_scopes: Sequence[Any],
    loc: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if isinstance(pred, (_And, _Or)):
        for expr in pred.exprs:
            findings.extend(_check_quantifier_scopes(expr, spec_scopes, loc))
    elif isinstance(pred, _Not):
        findings.extend(_check_quantifier_scopes(pred.expr, spec_scopes, loc))
    elif isinstance(pred, _Implies):
        findings.extend(_check_quantifier_scopes(pred.left, spec_scopes, loc))
        findings.extend(_check_quantifier_scopes(pred.right, spec_scopes, loc))
    elif isinstance(pred, (_ForAll, _Exists)):
        if pred.variable.scope not in spec_scopes:
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"Bound '{pred.variable.name}' uses Scope "
                    f"'{pred.variable.scope.id or pred.variable.scope.entity_cls.__name__}' "
                    f"not registered in spec.scopes",
                )
            )
        findings.extend(_check_quantifier_scopes(pred.predicate, spec_scopes, loc))
    elif isinstance(pred, _Present):
        target_scope = pred.target.scope
        if target_scope not in spec_scopes:
            name = pred.target.name if isinstance(pred.target, Bound) else repr(pred.target)
            findings.append(
                Finding(
                    Severity.ERROR,
                    loc,
                    f"Present target '{name}' uses Scope "
                    f"'{target_scope.id or target_scope.entity_cls.__name__}' "
                    f"not registered in spec.scopes",
                )
            )
    elif isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        findings.extend(_check_operand_scopes(pred.left, spec_scopes, loc))
        findings.extend(_check_operand_scopes(pred.right, spec_scopes, loc))
    elif isinstance(pred, _In):
        findings.extend(_check_operand_scopes(pred.operand, spec_scopes, loc))
        for value in pred.values:
            findings.extend(_check_operand_scopes(value, spec_scopes, loc))
    elif isinstance(pred, (_IsNull, _IsNotNull)):
        findings.extend(_check_operand_scopes(pred.operand, spec_scopes, loc))
    return findings


def _check_operand_scopes(
    operand: Any,
    spec_scopes: Sequence[Any],
    loc: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if isinstance(operand, _Count):
        if operand.variable.scope not in spec_scopes:
            findings.append(_unregistered_bound_scope(operand.variable, loc))
        findings.extend(_check_quantifier_scopes(operand.predicate, spec_scopes, loc))
    elif isinstance(operand, (_Sum, _Min, _Max)):
        if operand.variable.scope not in spec_scopes:
            findings.append(_unregistered_bound_scope(operand.variable, loc))
        findings.extend(_check_operand_scopes(operand.operand, spec_scopes, loc))
    elif isinstance(operand, Expr):
        findings.extend(_check_operand_scopes(operand.left, spec_scopes, loc))  # type: ignore[attr-defined]
        findings.extend(_check_operand_scopes(operand.right, spec_scopes, loc))  # type: ignore[attr-defined]
    return findings


def _unregistered_bound_scope(variable: Bound, loc: str) -> Finding:
    return Finding(
        Severity.ERROR,
        loc,
        f"Bound '{variable.name}' uses Scope "
        f"'{variable.scope.id or variable.scope.entity_cls.__name__}' "
        f"not registered in spec.scopes",
    )


def _operand_refs(operand: Any) -> list[FieldDescriptor | InstanceField]:
    """Field references inside an operand: a descriptor or an expression tree."""
    if is_field_ref(operand):
        return [operand]
    if isinstance(operand, _Count):
        refs: list[FieldDescriptor | InstanceField] = []
        for instance in operand.variable.scope:
            refs.extend(
                _collect_field_refs(bind_predicate(operand.predicate, operand.variable, instance))
            )
        return refs
    if isinstance(operand, (_Sum, _Min, _Max)):
        refs = []
        for instance in operand.variable.scope:
            refs.extend(_operand_refs(bind_operand(operand.operand, operand.variable, instance)))
        return refs
    if isinstance(operand, Expr):
        return _operand_refs(operand.left) + _operand_refs(operand.right)  # type: ignore[attr-defined]
    return []


def _collect_field_refs(pred: Predicate) -> list[FieldDescriptor | InstanceField]:
    refs: list[FieldDescriptor | InstanceField] = []
    if isinstance(pred, (_And, _Or)):
        for e in pred.exprs:
            refs.extend(_collect_field_refs(e))
    elif isinstance(pred, _Not):
        refs.extend(_collect_field_refs(pred.expr))
    elif isinstance(pred, _Implies):
        refs.extend(_collect_field_refs(pred.left))
        refs.extend(_collect_field_refs(pred.right))
    elif isinstance(pred, (_ForAll, _Exists)):
        for instance in pred.variable.scope:
            refs.extend(
                _collect_field_refs(bind_predicate(pred.predicate, pred.variable, instance))
            )
    elif isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        refs.extend(_operand_refs(pred.left))
        refs.extend(_operand_refs(pred.right))
    elif isinstance(pred, _In):
        refs.extend(_operand_refs(pred.operand))
        for value in pred.values:
            refs.extend(_operand_refs(value))
    elif isinstance(pred, (_IsNull, _IsNotNull)):
        refs.extend(_operand_refs(pred.operand))
    elif isinstance(pred, _Present):
        pass
    return refs


def _check_requires_cycles(
    actions: list[Action],
    action_by_id: dict[str, Action],
    findings: list[Finding],
    err_fn: Callable[[str, str], Finding],
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
                findings.append(
                    err_fn(
                        f"action:{action_id}",
                        f"circular dependency detected involving '{nid}'",
                    )
                )
                color[action_id] = BLACK
                return True
            if color[nid] == WHITE and dfs(nid):
                color[action_id] = BLACK
                return True
        color[action_id] = BLACK
        return False

    for action in actions:
        if color[action.id] == WHITE:
            dfs(action.id)


def _describe_operand(op: Any) -> str:
    if isinstance(op, BoundField):
        return repr(op)
    if is_field_ref(op):
        return repr(op)
    if isinstance(op, _Count):
        scope = op.variable.scope.id or op.variable.scope.entity_cls.__name__
        return f"COUNT {op.variable.name} IN {scope}: {_describe(op.predicate)}"
    if isinstance(op, (_Sum, _Min, _Max)):
        scope = op.variable.scope.id or op.variable.scope.entity_cls.__name__
        name = type(op).__name__[1:].upper()
        return f"{name} {op.variable.name} IN {scope}: {_describe_operand(op.operand)}"
    if isinstance(op, Expr):
        return (
            f"({_describe_operand(op.left)} {expr_op(op)} "  # type: ignore[attr-defined]
            f"{_describe_operand(op.right)})"  # type: ignore[attr-defined]
        )
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
    if isinstance(pred, _ForAll):
        scope = pred.variable.scope.id or pred.variable.scope.entity_cls.__name__
        return f"FORALL {pred.variable.name} IN {scope}: {_describe(pred.predicate)}"
    if isinstance(pred, _Exists):
        scope = pred.variable.scope.id or pred.variable.scope.entity_cls.__name__
        return f"EXISTS {pred.variable.name} IN {scope}: {_describe(pred.predicate)}"
    if isinstance(pred, _Present):
        return f"PRESENT({pred.target!r})"
    if isinstance(pred, _In):
        values = ", ".join(_describe_operand(value) for value in pred.values)
        return f"{_describe_operand(pred.operand)} in [{values}]"
    if isinstance(pred, _IsNull):
        return f"{_describe_operand(pred.operand)} is None"
    if isinstance(pred, _IsNotNull):
        return f"{_describe_operand(pred.operand)} is not None"
    return repr(pred)
