"""Projection for one-sided safety proofs (research/37)."""

from copyreg import dispatch_table
from dataclasses import dataclass
from typing import Any

from analint.models.action import Action
from analint.models.effect import Add, Create, Delete, Set, Subtract
from analint.models.predicate import _And
from analint.models.root import Spec
from analint.models.scope import InstanceRef, context_key_label
from analint.validator.kernel import _has_plain_copy
from analint.validator.slicing import (
    PRESENT,
    Slice,
    SliceAnalysis,
    Var,
    _entity_cls,
    _operand_vars,
    _pred_vars,
    _target_key,
    _Unsliceable,
    _whole_slot,
)
from analint.validator.structural import _collect_field_refs


def _label(var: Var) -> str:
    return f"{context_key_label(var[0])}.{var[1]}"


def _guard_vars(predicate: Any) -> set[Var]:
    variables: set[Var] = set()
    _pred_vars(predicate, variables)
    return variables


def _effect_vars(effect: Any) -> set[Var]:
    if isinstance(effect, (Create, Delete)):
        return _whole_slot(effect.target)
    if isinstance(effect, (Set, Add, Subtract)):
        return {(_target_key(effect), effect.field.field_name)}
    raise _Unsliceable(effect)


@dataclass
class Projection:
    spec: Spec
    variables: frozenset[Var]
    dropped: list[dict]

    @property
    def fields(self) -> list[str]:
        return sorted(map(_label, self.variables))

    def context(self, root: dict) -> dict:
        """Erase hidden values before any predicate or transition sees a root."""
        from analint.validator.explorer import _build_instance, _slot_value

        fields: dict = {}
        for key, field in self.variables:
            names = fields.setdefault(key, [])
            if field != PRESENT:
                names.append(field)
        projected = {}
        for key, inst in root.items():
            if key in fields:
                names = tuple(fields[key])
                scoped = isinstance(key, InstanceRef)
                projected[key] = _build_instance(
                    key, scoped, names, _slot_value(inst, scoped, names)
                )
        return projected


def derive(analysis: SliceAnalysis, predicate: Any, exact: Slice) -> Projection | None:
    """Follow all expanded writers to a fixed point over visible update inputs.

    Keep postconditions and payloads together with all of their inputs. Keep
    lifecycle fields on retained targets and whole slots for Create/Delete so
    the concrete kernel can enforce initialization and field constraints.
    Invariants are never used for pruning in this proof.
    """
    if exact.vars is None or not exact.vars or not analysis.sliceable:
        return None
    spec = analysis.spec
    # Custom copying/access can observe or change fields outside the DSL.
    if any(not _has_plain_copy(cls) or cls in dispatch_table for cls in spec.entities):
        return None
    state_types = set(spec.entities)
    try:
        variables = _guard_vars(predicate)
        if not variables:
            return None
        while True:
            previous = set(variables)
            writers = {id(action) for var in previous for action in analysis.writers.get(var, ())}
            for action in spec.actions:
                if id(action) not in writers:
                    continue
                for effect in action.effect:
                    targets = _effect_vars(effect)
                    if not targets & variables:
                        continue
                    variables.update(targets)
                    if isinstance(effect, Set):
                        _operand_vars(effect.value, variables)
                    elif isinstance(effect, (Add, Subtract)):
                        _operand_vars(effect.amount, variables)
                    elif isinstance(effect, Create):
                        for value in effect.fields.values():
                            _operand_vars(value, variables)
                    for key, _ in targets:
                        variables.update(
                            (key, lc.field_name)
                            for lc in spec.lifecycles
                            if lc.entity_cls is _entity_cls(key)
                        )
                for post in action.post:
                    _pred_vars(post, variables)
                for emitted in action.emits:
                    if not isinstance(emitted, type):
                        for value in emitted.__dict__.values():
                            _operand_vars(value, variables)
            variables.update(
                {(key, PRESENT) for key, _ in variables if isinstance(key, InstanceRef)}
            )
            if variables == previous:
                break
        if exact.vars <= variables or any(
            _entity_cls(key) not in state_types for key, _ in variables
        ):
            return None

        actions: list[Action] = []
        dropped = []
        for action in spec.actions:
            location = f"action:{action.id}"
            effects = [effect for effect in action.effect if _effect_vars(effect) & variables]
            if not effects:
                dropped.append(
                    {
                        "location": location,
                        "reason": "no retained writes",
                        "writes": sorted(
                            {
                                _label(var)
                                for effect in action.effect
                                for var in _effect_vars(effect)
                            }
                        ),
                    }
                )
                continue
            if any(
                ref.entity_cls not in state_types
                for guard in action.pre
                for ref in _collect_field_refs(guard)
            ):
                return None  # a relevant excluded writer cannot support a certificate
            pre = []
            for index, guard in enumerate(action.pre, 1):
                terms = guard.exprs if isinstance(guard, _And) else [guard]
                for term_index, term in enumerate(terms, 1):
                    if _guard_vars(term) <= variables:
                        pre.append(term)
                    else:
                        suffix = f".and[{term_index}]" if isinstance(guard, _And) else ""
                        dropped.append(
                            {
                                "location": location,
                                "element": f"pre[{index}]{suffix}",
                                "reason": "reads erased fields",
                            }
                        )
            for index, effect in enumerate(action.effect, 1):
                if not _effect_vars(effect) & variables:
                    dropped.append(
                        {
                            "location": location,
                            "element": f"effect[{index}]",
                            "reason": "writes only erased fields",
                        }
                    )
            actions.append(action.model_copy(update={"pre": pre, "effect": effects}))
        dropped.extend(
            {"location": f"invariant:{inv.id}", "reason": "pruning disabled"}
            for inv in spec.invariants
        )
    except _Unsliceable:
        return None
    return Projection(
        spec.model_copy(update={"actions": actions, "invariants": []}),
        frozenset(variables),
        dropped,
    )
