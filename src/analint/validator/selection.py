"""Select verification work without changing membership of the system model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analint.models.root import Spec


class SelectionError(ValueError):
    """Invalid invocation settings, distinct from a defect in the model."""

    def to_dict(self) -> dict:
        return {"schema": "analint.error/v1", "kind": "usage", "error": str(self), "details": []}


def _ids(values: list[str] | None, name: str) -> list[str] | None:
    if values is None:
        return None
    if not isinstance(values, (list, tuple)) or not values:
        raise SelectionError(f"{name} must be a non-empty list of identifiers")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise SelectionError(f"{name} must contain non-empty strings")
    return list(dict.fromkeys(values))


@dataclass
class Selection:
    scenarios: list
    flows: list
    queries: list
    invariants: list
    scope: dict[str, Any] | None


def select_checks(
    spec: Spec,
    checks: list[str] | None,
    scenario_ids: list[str] | None,
    tags: list[str] | None,
) -> Selection:
    checks = _ids(checks, "checks")
    # Empty legacy lists have always meant no scenario filter.
    scenario_ids = _ids(scenario_ids, "scenario_ids") if scenario_ids else None
    tags = _ids(tags, "tags") if tags else None
    groups = {"flow": spec.flows, "query": spec.queries, "invariant": spec.invariants}
    chosen: set[int] = set()
    if checks is not None:
        for selector in checks:
            prefix, separator, name = selector.partition(":")
            if separator and prefix in groups:
                matches = [obj for obj in groups[prefix] if obj.id == name]
            else:
                matches = [obj for group in groups.values() for obj in group if obj.id == selector]
            if not matches:
                raise SelectionError(
                    f"unknown check '{selector}'; use a flow, query or invariant id"
                )
            if len(matches) != 1:
                raise SelectionError(
                    f"ambiguous check '{selector}'; qualify it as flow:ID, query:ID or invariant:ID"
                )
            chosen.add(id(matches[0]))
    else:
        chosen = {id(obj) for group in groups.values() for obj in group}

    scenarios = spec.scenarios if checks is None or scenario_ids or tags else []
    if scenario_ids:
        missing = set(scenario_ids) - {scenario.id for scenario in spec.scenarios}
        if missing:
            raise SelectionError(f"unknown scenario ids: {', '.join(sorted(missing))}")
        scenarios = [sc for sc in scenarios if sc.id in scenario_ids]
    if tags:
        missing = set(tags) - {tag for scenario in spec.scenarios for tag in scenario.tags}
        if missing:
            raise SelectionError(f"unknown scenario tags: {', '.join(sorted(missing))}")
        scenarios = [sc for sc in scenarios if any(tag in sc.tags for tag in tags)]
    if (scenario_ids or tags) and not scenarios:
        raise SelectionError("scenario/tag filters match no scenarios")

    flows = [flow for flow in spec.flows if id(flow) in chosen]
    queries = [query for query in spec.queries if id(query) in chosen]
    requested_invariants = [inv for inv in spec.invariants if id(inv) in chosen]
    # Reachability includes per-action defect coverage over the entire model.
    # Retain the existing canonical invariant proofs/trust phase for that work,
    # rather than granting trust to an unselected invariant or changing pruning.
    invariants = spec.invariants if queries or requested_invariants else []
    if checks is None:
        invariants = spec.invariants
    scope = None
    if checks is not None or scenario_ids or tags:
        requested = [f"scenario:{sc.id}" for sc in scenarios] + [
            f"{kind}:{obj.id}"
            for kind, group in groups.items()
            for obj in group
            if id(obj) in chosen
        ]
        supporting = [f"invariant:{inv.id}" for inv in invariants if id(inv) not in chosen]
        assessed = set(requested + supporting)
        scope = {
            "mode": "selected",
            "requested": requested,
            "supporting": supporting,
            "not_selected": [
                f"{kind}:{obj.id}"
                for kind, group in {"scenario": spec.scenarios, **groups}.items()
                for obj in group
                if f"{kind}:{obj.id}" not in assessed
            ],
            "model_actions": [action.id for action in spec.actions],
            "action_coverage": "reachability" if queries or invariants else "executed_steps_only",
            "excluded_actions": {},
        }
    return Selection(scenarios, flows, queries, invariants, scope)
