"""Deterministic exploration artifact (P4.1)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from analint import (
    Action,
    Add,
    Create,
    Delete,
    Entity,
    Event,
    Field,
    Scope,
    Set,
    Spec,
)
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


def test_oauth_summary_states_and_edges():
    summary = _example_artifact("oauth")["summary"]
    assert summary["states"] == 1169
    assert summary["edges"] == 2256
    assert summary["complete"] is True
    assert summary["incomplete_reasons"] == []


def test_artifact_is_deterministic_in_process():
    assert _example_artifact("branch_protection") == _example_artifact("branch_protection")


def test_artifact_is_deterministic_across_processes():
    # Hash randomization differs per process; the artifact must not.
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
    # round-trips through json without loss
    assert json.loads(json.dumps(d)) == d


def test_parameterized_actions_expose_family_and_bindings():
    edges = _example_artifact("oauth")["edges"]
    param_edges = [e for e in edges if e["bindings"]]
    assert param_edges, "expected parameterized edges in oauth"
    sample = param_edges[0]
    assert sample["action"] == "issue_code"  # the family, not the suffixed id
    assert set(sample["bindings"]) == {"code", "code_id", "client", "redirect", "challenge"}
    assert all(isinstance(v, str) for v in sample["bindings"].values())


def test_multi_root_preserves_distinct_indices():
    d = _example_artifact("mafia")
    assert d["summary"]["roots"] > 1
    indices = [root["index"] for root in d["roots"]]
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices) > 1
    # every declared root index points at a real node
    node_ids = {n["id"] for n in d["nodes"]}
    assert all(root["node"] in node_ids for root in d["roots"])


# ── targeted inline specs ───────────────────────────────────────────────────────


def test_depth_and_diff_are_correct():
    class Counter(Entity):
        n: int = Field(0, ge=0, le=2)

    tick = Action(id="tick", pre=[Counter.n < 2], effect=[Add(Counter.n, 1)])
    spec = Spec(id="counter", name="Counter", entities=[Counter], actions=[tick])
    d = _artifact_dict(spec)

    by_id = {n["id"]: n for n in d["nodes"]}
    root = next(n for n in d["nodes"] if n["parent"] is None)
    assert root["depth"] == 0 and root["diff"] == {}
    # the BFS chain n=0 -> n=1 -> n=2
    assert d["summary"]["states"] == 3
    assert d["summary"]["max_depth"] == 2
    child = next(n for n in d["nodes"] if n["depth"] == 1)
    assert by_id[child["parent"]]["depth"] == 0
    assert child["diff"] == {"Counter.n": {"from": "0", "to": "1"}}


def test_self_loops_and_duplicate_target_edges_are_visible():
    class Counter(Entity):
        n: int = Field(0, ge=0, le=2)

    tick = Action(id="tick", pre=[Counter.n < 2], effect=[Add(Counter.n, 1)])
    reset = Action(id="reset", effect=[Set(Counter.n, 0)])  # self-loop at n=0; →n=0 from n=1,2
    spec = Spec(id="loops", name="Loops", entities=[Counter], actions=[tick, reset])
    d = _artifact_dict(spec)

    self_loops = [e for e in d["edges"] if e["source"] == e["target"]]
    assert self_loops, "a self-loop edge (reset at n=0) must remain visible"
    targets = [e["target"] for e in d["edges"]]
    assert any(targets.count(t) > 1 for t in set(targets)), "duplicate-target edges must remain"


def test_capped_and_excluded_can_coexist():
    class Box(Entity):
        n: int = Field(0, ge=0, le=5)

    class Ping(Event):
        x: int = 0

    grow = Action(id="grow", pre=[Box.n < 5], effect=[Add(Box.n, 1)])
    # pre references an Event payload field — outside the explored state → excluded
    handle = Action(id="handle", pre=[Ping.x == 0], effect=[Set(Box.n, 0)])
    spec = Spec(
        id="ce", name="CE", entities=[Box], events=[Ping], actions=[grow, handle], max_states=3
    )
    summary = _artifact_dict(spec)["summary"]

    assert summary["incomplete_reasons"] == ["capped", "excluded-semantics"]
    assert summary["complete"] is False


def test_create_delete_and_presence_serialize():
    class Item(Entity):
        tag: int = Field(0, ge=0, le=1)

    items = Scope(Item, keys=["a"])
    a = items["a"]
    # Create/Delete carry their own presence guards in the kernel (create-on-present
    # and delete-on-absent are rejected), so no explicit precondition is needed.
    drop = Action(id="drop", effect=[Delete(a)])
    make = Action(id="make", effect=[Create(a)])
    spec = Spec(
        id="presence", name="Presence", entities=[Item], scopes=[items], actions=[drop, make]
    )
    d = _artifact_dict(spec)

    presence_keys = [k for node in d["nodes"] for k in node["state"] if k.endswith(".@present")]
    assert presence_keys, "presence (@present) must appear in serialized state"
    # an absent state and a present state are both reachable
    present_values = {node["state"].get("Item['a'].@present") for node in d["nodes"]}
    assert "True" in present_values and "False" in present_values
