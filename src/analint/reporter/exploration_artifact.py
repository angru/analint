"""The deterministic, versioned view of one bounded exploration (P4.1).

The stable contract is the JSON shape ``analint.exploration/v1`` documented in
research/26 (``schema``/``spec``/``source``/``completeness``/``summary``/
``findings``/``graph``), not these Python classes — they are internal and not
exported from ``analint.__init__``. Node and edge IDs are SHA-256 digests of
canonical JSON content, so the artifact is identical across runs and processes.
The builder lives in ``analint.validator.artifact_builder``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

ARTIFACT_SCHEMA = "analint.exploration/v1"


def canonical_digest(content: Any) -> str:
    """``sha256:<hex>`` over canonical JSON — the stable id of a node or edge."""
    encoded = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def json_scalar(value: Any) -> Any:
    """A JSON-native value for a state field: enums use the stable
    ``TypeName.MEMBER`` spelling; bool/int/float/str/None pass through."""
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def render_scalar(value: Any) -> str:
    """A string label for an action binding value (instance ref / enum / scalar)."""
    from analint.models.scope import InstanceRef, context_key_label

    if isinstance(value, InstanceRef):
        return context_key_label(value)
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    return repr(value)


@dataclass(frozen=True)
class ArtifactNode:
    id: str
    depth: int
    parent_edge: str | None  # the BFS shortest-path-tree incoming edge; None at a root
    state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "depth": self.depth,
            "parent_edge": self.parent_edge,
            "state": self.state,
        }


@dataclass(frozen=True)
class ArtifactEdge:
    id: str
    source: str
    target: str
    action: str  # the concrete executable action id (do not parse it)
    family: str  # the parameterized family, "" for a plain action
    binding: dict[str, str]
    changes: list[dict[str, Any]]  # [{"field", "before", "after"}], before/after JSON-native

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "action": self.action,
            "family": self.family,
            "binding": self.binding,
            "changes": self.changes,
        }


@dataclass
class ExplorationArtifact:
    spec: dict[str, Any]
    source: dict[str, Any]
    completeness: dict[str, Any]
    summary: dict[str, Any]
    findings: list[dict[str, str]]
    roots: list[dict[str, Any]]  # [{"index": int, "node": id}]
    nodes: list[ArtifactNode] = field(default_factory=list)
    edges: list[ArtifactEdge] = field(default_factory=list)
    graph_included: bool = True
    graph_omitted_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """The versioned wire contract — only strings, numbers, bools, None, lists
        and string-keyed dicts. A compact projection sets ``graph`` to ``null`` and
        adds an explicit ``graph_omitted`` reason (output truncation is NOT an
        exploration-incompleteness reason)."""
        payload: dict[str, Any] = {
            "schema": ARTIFACT_SCHEMA,
            "spec": self.spec,
            "source": self.source,
            "completeness": self.completeness,
            "summary": self.summary,
            "findings": self.findings,
        }
        if self.graph_included:
            payload["graph"] = {
                "roots": self.roots,
                "nodes": [n.to_dict() for n in self.nodes],
                "edges": [e.to_dict() for e in self.edges],
            }
        else:
            payload["graph"] = None
            payload["graph_omitted"] = self.graph_omitted_reason or "graph omitted"
        return payload
