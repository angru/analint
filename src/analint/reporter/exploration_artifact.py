"""A deterministic, fully serializable view of one bounded exploration (P4.1).

These DTOs are internal — the stable contract is the versioned JSON shape
(``analint.exploration/v1``) produced by ``to_dict()``, not the Python classes.
The builder lives in ``analint.validator.artifact_builder``; this module holds the
shapes and the canonical scalar rendering so nothing downstream re-derives how a
domain value becomes a string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

ARTIFACT_VERSION = "analint.exploration/v1"


def render_scalar(value: Any) -> str:
    """Canonical string for a domain scalar / instance reference / enum.

    Mirrors ``explorer._value_str`` for plain values so a node's state and an
    action's bindings render identically, and labels instance references like the
    state renderer does (never leaking an ``InstanceRef`` object into JSON)."""
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
    parent: str | None
    root_index: int
    via: dict[str, Any] | None  # {"action": str, "bindings"?: {name: str}} — None at a root
    state: dict[str, str]
    # changed field → {"from": value, "to": value}; a value is None when the field
    # only exists on one side (a slot appearing/disappearing via Create/Delete).
    diff: dict[str, dict[str, str | None]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "depth": self.depth,
            "parent": self.parent,
            "root_index": self.root_index,
            "via": self.via,
            "state": self.state,
            "diff": self.diff,
        }


@dataclass(frozen=True)
class ArtifactEdge:
    id: str
    source: str
    target: str
    action: str  # the action family (parameterized) or id (plain)
    bindings: dict[str, str] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "action": self.action,
            "bindings": self.bindings,
        }


@dataclass
class ExplorationArtifact:
    summary: dict[str, Any]
    roots: list[dict[str, Any]]
    nodes: list[ArtifactNode] = field(default_factory=list)
    edges: list[ArtifactEdge] = field(default_factory=list)
    fired_actions: list[str] = field(default_factory=list)
    excluded_actions: list[dict[str, str]] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """The versioned, JSON-ready contract — only strings, numbers, bools,
        None, lists and string-keyed dicts."""
        return {
            "version": ARTIFACT_VERSION,
            "summary": self.summary,
            "roots": self.roots,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "fired_actions": self.fired_actions,
            "excluded_actions": self.excluded_actions,
            "findings": self.findings,
        }
