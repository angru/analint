"""Build a deterministic exploration artifact from one `Exploration` (P4.1).

This adapts the existing BFS result (`states`, `order`, `edges`, `parents`,
`roots`, `fired`, `excluded`, `capped`) into the versioned DTO. It does not
re-run or rewrite the search, and it reuses ``render_state`` for field discovery
so node states match what the rest of the engine prints.
"""

from __future__ import annotations

from statistics import fmean

from analint.models.root import Spec
from analint.reporter.exploration_artifact import (
    ArtifactEdge,
    ArtifactNode,
    ExplorationArtifact,
    render_scalar,
)
from analint.validator.explorer import Exploration, render_state


def build_exploration_artifact(exp: Exploration, spec: Spec) -> ExplorationArtifact:
    actions_by_id = {action.id: action for action in spec.actions}
    # BFS order is a deterministic list (driven by the ordered spec.actions), so
    # index-based node ids are stable across runs and processes.
    node_id = {key: f"n{i}" for i, key in enumerate(exp.order)}
    rendered = {key: render_state(exp.states[key]) for key in exp.order}

    def action_view(action_id: str) -> tuple[str, dict[str, str] | None]:
        action = actions_by_id.get(action_id)
        if action is None:
            return action_id, None
        if action.family:
            bindings = {
                name: render_scalar(value) for name, value in (action._bindings or {}).items()
            }
            return action.family, bindings
        return action.id, None

    nodes: list[ArtifactNode] = []
    for key in exp.order:
        prev, action_id = exp.parents[key]
        via: dict | None = None
        diff: dict[str, dict[str, str | None]] = {}
        if prev is not None:
            family, bindings = action_view(action_id)
            via = {"action": family}
            if bindings is not None:
                via["bindings"] = bindings
            diff = _diff(rendered[prev], rendered[key])
        nodes.append(
            ArtifactNode(
                id=node_id[key],
                depth=len(exp.trace_to(key)),
                parent=node_id[prev] if prev is not None else None,
                root_index=exp.roots.get(exp.root_of(key), 1),
                via=via,
                state=rendered[key],
                diff=diff,
            )
        )

    edges: list[ArtifactEdge] = []
    for index, (source, action_id, target) in enumerate(exp.edges):
        # A capped run may record an edge to a state beyond the budget; keep the
        # artifact internally consistent by emitting only edges between nodes.
        if source not in node_id or target not in node_id:
            continue
        family, bindings = action_view(action_id)
        edges.append(
            ArtifactEdge(
                id=f"e{index}",
                source=node_id[source],
                target=node_id[target],
                action=family,
                bindings=bindings,
            )
        )

    out_degree = dict.fromkeys(node_id.values(), 0)
    for edge in edges:
        out_degree[edge.source] += 1
    counts = list(out_degree.values())
    branching = {
        "min": min(counts) if counts else 0,
        "max": max(counts) if counts else 0,
        "mean": round(fmean(counts), 4) if counts else 0.0,
    }

    reasons: list[str] = []
    if exp.capped:
        reasons.append("capped")
    if exp.excluded:
        reasons.append("excluded-semantics")
    reasons.sort()

    summary = {
        "roots": len(exp.roots),
        "states": len(exp.order),
        "edges": len(edges),
        "max_depth": max((node.depth for node in nodes), default=0),
        "fired_actions": len(exp.fired),
        "dead_ends": sum(1 for count in counts if count == 0),
        "branching": branching,
        "complete": not reasons,
        "incomplete_reasons": reasons,
    }

    roots = sorted(
        ({"node": node_id[key], "index": index} for key, index in exp.roots.items()),
        key=lambda root: root["index"],
    )
    excluded_actions = sorted(
        ({"action": action_id, "reason": reason} for action_id, reason in exp.excluded.items()),
        key=lambda item: item["action"],
    )
    findings = [
        {"severity": f.severity.value, "location": f.location, "message": f.message}
        for f in exp.findings
    ]

    return ExplorationArtifact(
        summary=summary,
        roots=roots,
        nodes=nodes,
        edges=edges,
        fired_actions=sorted(exp.fired),
        excluded_actions=excluded_actions,
        findings=findings,
    )


def _diff(before: dict[str, str], after: dict[str, str]) -> dict[str, dict[str, str | None]]:
    changed: dict[str, dict[str, str | None]] = {}
    for field_label in sorted(set(before) | set(after)):
        old = before.get(field_label)
        new = after.get(field_label)
        if old != new:
            changed[field_label] = {"from": old, "to": new}
    return changed
