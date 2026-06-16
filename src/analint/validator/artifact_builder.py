"""Build the deterministic ``analint.exploration/v1`` artifact from one
`Exploration` (P4.1, schema in research/26).

This adapts the existing BFS result (`states`, `order`, `edges`, `parents`,
`roots`, `fired`, `excluded`, `capped`) into the documented wire contract. It does
not re-run or rewrite the search, and it reuses ``context_key_label``, presence
semantics and ``all_fields`` for state rendering — no duplicate field discovery
and no second ``step()``.
"""

from __future__ import annotations

from collections import Counter
from statistics import fmean
from typing import Any

from analint.models.entity import all_fields
from analint.models.root import Spec
from analint.models.scope import InstanceRef, context_key_label
from analint.reporter.exploration_artifact import (
    ArtifactEdge,
    ArtifactNode,
    ExplorationArtifact,
    canonical_digest,
    json_scalar,
    render_scalar,
)
from analint.validator.explorer import Exploration, is_present


def _render_state(ctx: dict) -> dict[str, Any]:
    """Canonical, JSON-native state map: enums as ``TypeName.MEMBER``, presence as
    a bool, every other field value JSON-native. Keys use ``context_key_label``."""
    out: dict[str, Any] = {}
    for key in sorted(ctx, key=context_key_label):
        inst = ctx[key]
        label = context_key_label(key)
        if isinstance(key, InstanceRef):
            present = is_present(ctx, key)
            out[f"{label}.@present"] = present
            if not present:
                continue
        for field_name in sorted(all_fields(type(inst))):
            out[f"{label}.{field_name}"] = json_scalar(inst.__dict__.get(field_name))
    return out


def build_exploration_artifact(
    exp: Exploration,
    spec: Spec,
    *,
    source_kind: str = "canonical",
    query_id: str | None = None,
    max_states: int | None = None,
) -> ExplorationArtifact:
    actions_by_id = {action.id: action for action in spec.actions}
    rendered = {key: _render_state(exp.states[key]) for key in exp.order}
    node_id = {key: canonical_digest(rendered[key]) for key in exp.order}

    def family_of(action_id: str) -> str:
        action = actions_by_id.get(action_id)
        return action.family if (action is not None and action.family) else action_id

    def binding_of(action_id: str) -> dict[str, str]:
        action = actions_by_id.get(action_id)
        if action is None or not action._bindings:
            return {}
        return {name: render_scalar(value) for name, value in action._bindings.items()}

    def edge_digest(source_key: Any, action_id: str, target_key: Any) -> str:
        return canonical_digest(
            {"source": node_id[source_key], "action": action_id, "target": node_id[target_key]}
        )

    nodes: list[ArtifactNode] = []
    for key in exp.order:
        prev, action_id = exp.parents[key]
        parent_edge = edge_digest(prev, action_id, key) if prev is not None else None
        nodes.append(
            ArtifactNode(
                id=node_id[key],
                depth=len(exp.trace_to(key)),
                parent_edge=parent_edge,
                state=rendered[key],
            )
        )

    edges: list[ArtifactEdge] = []
    for source_key, action_id, target_key in exp.edges:
        # A capped run may record an edge to a state beyond the budget; keep the
        # artifact internally consistent by emitting only edges between nodes.
        if source_key not in node_id or target_key not in node_id:
            continue
        edges.append(
            ArtifactEdge(
                id=edge_digest(source_key, action_id, target_key),
                source=node_id[source_key],
                target=node_id[target_key],
                action=action_id,
                family=family_of(action_id),
                binding=binding_of(action_id),
                changes=_changes(rendered[source_key], rendered[target_key]),
            )
        )

    out_degree = Counter(edge.source for edge in edges)
    counts = [out_degree.get(node.id, 0) for node in nodes]
    self_loops = sum(1 for edge in edges if edge.source == edge.target)

    reasons: list[str] = []
    if exp.capped:
        reasons.append("capped")
    if exp.excluded:
        reasons.append("excluded-semantics")
    reasons.sort()

    fired = sorted({family_of(action_id) for action_id in exp.fired})
    edge_count_by_action = dict(sorted(Counter(edge.family for edge in edges).items()))
    excluded_actions = {action_id: reason for action_id, reason in sorted(exp.excluded.items())}

    summary = {
        "roots": len(exp.roots),
        "states": len(exp.order),
        "edges": len(edges),
        "max_depth": max((node.depth for node in nodes), default=0),
        "dead_ends": sum(1 for count in counts if count == 0),
        "self_loops": self_loops,
        "branching": {
            "min": min(counts) if counts else 0,
            "mean": round(fmean(counts), 4) if counts else 0.0,
            "max": max(counts) if counts else 0,
        },
        "fired_actions": fired,
        "edge_count_by_action": edge_count_by_action,
        "excluded_actions": excluded_actions,
    }

    roots = sorted(
        ({"index": index, "node": node_id[key]} for key, index in exp.roots.items()),
        key=lambda root: root["index"],
    )
    findings = [
        {"severity": f.severity.value, "location": f.location, "message": f.message}
        for f in exp.findings
    ]

    return ExplorationArtifact(
        spec={"id": spec.id, "version": spec.version},
        source={"kind": source_kind, "query": query_id},
        completeness={
            "complete": not reasons,
            "reasons": reasons,
            "max_states": spec.max_states if max_states is None else max_states,
        },
        summary=summary,
        findings=findings,
        roots=roots,
        nodes=nodes,
        edges=edges,
    )


def _changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field_label in sorted(set(before) | set(after)):
        old = before.get(field_label)
        new = after.get(field_label)
        if old != new:
            changes.append({"field": field_label, "before": old, "after": new})
    return changes
