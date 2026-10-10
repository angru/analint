"""Build the ``analint.exploration/v1`` artifact from one `Exploration` (P4.1/P4.4).

Two builders share one summary computation:

- ``build_exploration_artifact`` — the full artifact (nodes/edges/graph): renders
  every state and computes a SHA-256 digest per node/edge.
- ``build_summary_artifact`` — the compact projection (``graph: null``): the same
  summary and completeness WITHOUT rendering states or hashing, so the common
  compact CLI/MCP path does not materialise the whole graph (P4.4b; the full build
  was 28–88% of exploration time, research/26).

Neither re-runs the search; both reuse ``context_key_label``, presence semantics
and ``all_fields`` for any rendering — no duplicate field discovery, no second
``step()``.
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


def _family_of(actions_by_id: dict, action_id: str) -> str:
    action = actions_by_id.get(action_id)
    return action.family if (action is not None and action.family) else action_id


def _depths(exp: Exploration) -> list[int]:
    """BFS depth of every state, in one pass: a parent always precedes its child."""
    depth = [0] * len(exp.keys)
    for idx, parent in enumerate(exp.parent):
        if parent >= 0:
            depth[idx] = depth[parent] + 1
    return depth


def _summary(
    exp: Exploration, spec: Spec, actions_by_id: dict, max_states: int | None
) -> tuple[dict, dict]:
    """Summary + completeness computed straight from the exploration's integer
    arrays (no rendering, no digests). Every recorded edge joins two explored
    states: a target is stored before its edge."""
    out_degree = Counter(exp.edge_src)
    counts = [out_degree.get(idx, 0) for idx in range(len(exp.keys))]
    by_action = Counter(exp.edge_action)

    reasons: list[str] = []
    if exp.capped:
        reasons.append("capped")
    if exp.excluded:
        reasons.append("excluded-semantics")
    reasons.sort()

    families: Counter = Counter()
    for code, count in by_action.items():
        families[_family_of(actions_by_id, exp.action_ids[code])] += count
    summary = {
        "roots": len(exp.roots),
        "states": len(exp.order),
        "edges": len(exp.edge_src),
        "max_depth": max(_depths(exp), default=0),
        "dead_ends": sum(1 for count in counts if count == 0),
        "self_loops": sum(
            1 for src, dst in zip(exp.edge_src, exp.edge_dst, strict=True) if src == dst
        ),
        "branching": {
            "min": min(counts) if counts else 0,
            "mean": round(fmean(counts), 4) if counts else 0.0,
            "max": max(counts) if counts else 0,
        },
        "fired_actions": sorted({_family_of(actions_by_id, a) for a in exp.fired}),
        "edge_count_by_action": dict(sorted(families.items())),
        "excluded_actions": {aid: reason for aid, reason in sorted(exp.excluded.items())},
    }
    completeness = {
        "complete": not reasons,
        "reasons": reasons,
        "max_states": spec.max_states if max_states is None else max_states,
    }
    return summary, completeness


def _findings(exp: Exploration) -> list[dict[str, str]]:
    return [
        {"severity": f.severity.value, "location": f.location, "message": f.message}
        for f in exp.findings
    ]


def build_exploration_artifact(
    exp: Exploration,
    spec: Spec,
    *,
    source_kind: str = "canonical",
    query_id: str | None = None,
    max_states: int | None = None,
) -> ExplorationArtifact:
    actions_by_id = {action.id: action for action in spec.actions}
    summary, completeness = _summary(exp, spec, actions_by_id, max_states)
    depths = _depths(exp)

    rendered = {key: _render_state(exp.states[key]) for key in exp.order}
    node_id = {key: canonical_digest(rendered[key]) for key in exp.order}

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
    for idx, key in enumerate(exp.order):
        prev, action_id = exp.parents[key]
        nodes.append(
            ArtifactNode(
                id=node_id[key],
                depth=depths[idx],
                parent_edge=edge_digest(prev, action_id, key) if prev is not None else None,
                state=rendered[key],
            )
        )

    edges = [
        ArtifactEdge(
            id=edge_digest(source_key, action_id, target_key),
            source=node_id[source_key],
            target=node_id[target_key],
            action=action_id,
            family=_family_of(actions_by_id, action_id),
            binding=binding_of(action_id),
            changes=_changes(rendered[source_key], rendered[target_key]),
        )
        for source_key, action_id, target_key in exp.edges
    ]

    roots = sorted(
        ({"index": index, "node": node_id[key]} for key, index in exp.roots.items()),
        key=lambda root: root["index"],
    )
    return ExplorationArtifact(
        spec={"id": spec.id, "version": spec.version},
        source={"kind": source_kind, "query": query_id},
        completeness=completeness,
        summary=summary,
        findings=_findings(exp),
        roots=roots,
        nodes=nodes,
        edges=edges,
    )


def build_summary_artifact(
    exp: Exploration,
    spec: Spec,
    *,
    source_kind: str = "canonical",
    query_id: str | None = None,
    max_states: int | None = None,
    graph_omitted_reason: str | None = None,
) -> ExplorationArtifact:
    """The compact projection: full summary/completeness, ``graph: null``, without
    rendering states or hashing nodes/edges."""
    actions_by_id = {action.id: action for action in spec.actions}
    summary, completeness = _summary(exp, spec, actions_by_id, max_states)
    return ExplorationArtifact(
        spec={"id": spec.id, "version": spec.version},
        source={"kind": source_kind, "query": query_id},
        completeness=completeness,
        summary=summary,
        findings=_findings(exp),
        roots=[],
        graph_included=False,
        graph_omitted_reason=graph_omitted_reason or "summary-only build (graph not materialised)",
    )


def _changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field_label in sorted(set(before) | set(after)):
        old = before.get(field_label)
        new = after.get(field_label)
        if old != new:
            changes.append({"field": field_label, "before": old, "after": new})
    return changes
