"""Deterministic exploration artifact, schema analint.exploration/v1 (P4.1)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from analint import Action, Add, Create, Delete, Entity, Event, Field, Scope, Set, Spec
from analint.validator.artifact_builder import build_exploration_artifact
from analint.validator.engine import build_spec
from analint.validator.explorer import build_canonical_initials, explore

EXAMPLES = Path(__file__).parent.parent / "examples"


def _artifact_dict(spec: Spec) -> dict:
    initials, error = build_canonical_initials(spec)
    assert initials is not None, error
    exp = explore(spec, initials, spec.max_states)
    return build_exploration_artifact(exp, spec).to_dict()


def _example_artifact(name: str) -> dict:
    spec, _, _ = build_spec(EXAMPLES / name)
    return _artifact_dict(spec)


# ── examples ──────────────────────────────────────────────────────────────────


def test_oauth_schema_summary_and_completeness():
    d = _example_artifact("oauth")
    assert d["schema"] == "analint.exploration/v1"
    assert d["spec"]["id"] == "oauth"
    assert d["source"] == {"kind": "canonical", "query": None}
    assert d["summary"]["states"] == 1169
    assert d["summary"]["edges"] == 2256
    assert d["completeness"]["complete"] is True
    assert d["completeness"]["reasons"] == []
    assert len(d["graph"]["nodes"]) == 1169
    assert len(d["graph"]["edges"]) == 2256


def test_node_and_edge_ids_are_content_digests():
    d = _example_artifact("branch_protection")
    assert all(n["id"].startswith("sha256:") for n in d["graph"]["nodes"])
    assert all(e["id"].startswith("sha256:") for e in d["graph"]["edges"])
    # roots have no parent edge; non-roots reference a real edge id
    edge_ids = {e["id"] for e in d["graph"]["edges"]}
    roots = {r["node"] for r in d["graph"]["roots"]}
    for node in d["graph"]["nodes"]:
        if node["id"] in roots:
            assert node["parent_edge"] is None
        else:
            assert node["parent_edge"] in edge_ids


def test_artifact_is_deterministic_in_process():
    assert _example_artifact("branch_protection") == _example_artifact("branch_protection")


def test_artifact_is_deterministic_across_processes():
    # Hash randomization differs per process; SHA-digest ids must not.
    code = (
        "import json;from pathlib import Path;"
        "from analint.validator.engine import build_spec;"
        "from analint.validator.explorer import build_canonical_initials, explore;"
        "from analint.validator.artifact_builder import build_exploration_artifact;"
        "s,_,_=build_spec(Path('examples/branch_protection'));"
        "i,_=build_canonical_initials(s);"
        "print(json.dumps(build_exploration_artifact(explore(s,i,s.max_states),s).to_dict()))"
    )
    env = {**os.environ, "PYTHONHASHSEED": "1"}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=EXAMPLES.parent
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == _example_artifact("branch_protection")


def test_artifact_contains_only_json_primitives():
    d = _example_artifact("oauth")

    def check(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert isinstance(key, str), f"non-string dict key: {key!r}"
                check(value)
        elif isinstance(node, list):
            for item in node:
                check(item)
        else:
            assert isinstance(node, (str, int, float, bool)) or node is None, (
                f"non-primitive leaf in artifact: {type(node)}"
            )

    check(d)
    assert json.loads(json.dumps(d)) == d


def test_edges_preserve_concrete_action_family_and_binding():
    edges = _example_artifact("oauth")["graph"]["edges"]
    param_edges = [e for e in edges if e["family"] != e["action"]]
    assert param_edges, "expected parameterized edges in oauth"
    sample = next(e for e in param_edges if e["family"] == "issue_code")
    assert sample["action"].startswith("issue_code(")  # the concrete executable id is preserved
    assert set(sample["binding"]) == {"code", "code_id", "client", "redirect", "challenge"}
    assert all(isinstance(v, str) for v in sample["binding"].values())


def test_multi_root_preserves_distinct_indices():
    d = _example_artifact("mafia")
    assert d["summary"]["roots"] > 1
    indices = [root["index"] for root in d["graph"]["roots"]]
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices) > 1
    node_ids = {n["id"] for n in d["graph"]["nodes"]}
    assert all(root["node"] in node_ids for root in d["graph"]["roots"])


# ── targeted inline specs ───────────────────────────────────────────────────────


def test_depth_and_edge_changes_are_correct():
    class Counter(Entity):
        n: int = Field(0, ge=0, le=2)

    tick = Action(id="tick", pre=[Counter.n < 2], effect=[Add(Counter.n, 1)])
    spec = Spec(id="counter", name="Counter", entities=[Counter], actions=[tick])
    d = _artifact_dict(spec)

    assert d["summary"]["states"] == 3
    assert d["summary"]["max_depth"] == 2
    roots = {r["node"] for r in d["graph"]["roots"]}
    root = next(n for n in d["graph"]["nodes"] if n["id"] in roots)
    assert root["depth"] == 0 and root["parent_edge"] is None
    # the change appears on the EDGE, with JSON-native before/after
    changes = [c for e in d["graph"]["edges"] for c in e["changes"]]
    assert {"field": "Counter.n", "before": 0, "after": 1} in changes


def test_self_loops_and_duplicate_target_edges_are_visible():
    class Counter(Entity):
        n: int = Field(0, ge=0, le=2)

    tick = Action(id="tick", pre=[Counter.n < 2], effect=[Add(Counter.n, 1)])
    reset = Action(id="reset", effect=[Set(Counter.n, 0)])  # self-loop at n=0; →n=0 from n=1,2
    spec = Spec(id="loops", name="Loops", entities=[Counter], actions=[tick, reset])
    d = _artifact_dict(spec)

    edges = d["graph"]["edges"]
    assert d["summary"]["self_loops"] >= 1
    assert any(e["source"] == e["target"] for e in edges)
    targets = [e["target"] for e in edges]
    assert any(targets.count(t) > 1 for t in set(targets)), "duplicate-target edges must remain"


def test_capped_and_excluded_can_coexist():
    class Box(Entity):
        n: int = Field(0, ge=0, le=5)

    class Ping(Event):
        x: int = 0

    grow = Action(id="grow", pre=[Box.n < 5], effect=[Add(Box.n, 1)])
    handle = Action(id="handle", pre=[Ping.x == 0], effect=[Set(Box.n, 0)])  # Event pre → excluded
    spec = Spec(
        id="ce", name="CE", entities=[Box], events=[Ping], actions=[grow, handle], max_states=3
    )
    d = _artifact_dict(spec)

    assert d["completeness"]["reasons"] == ["capped", "excluded-semantics"]
    assert d["completeness"]["complete"] is False
    assert "handle" in d["summary"]["excluded_actions"]


def test_create_delete_and_presence_serialize():
    class Item(Entity):
        tag: int = Field(0, ge=0, le=1)

    items = Scope(Item, keys=["a"])
    a = items["a"]
    # Create/Delete carry their own presence guards in the kernel, so no explicit pre.
    drop = Action(id="drop", effect=[Delete(a)])
    make = Action(id="make", effect=[Create(a)])
    spec = Spec(
        id="presence", name="Presence", entities=[Item], scopes=[items], actions=[drop, make]
    )
    d = _artifact_dict(spec)

    presence_values = {node["state"].get("Item['a'].@present") for node in d["graph"]["nodes"]}
    # presence is a JSON bool, and both present and absent states are reachable
    assert True in presence_values and False in presence_values
