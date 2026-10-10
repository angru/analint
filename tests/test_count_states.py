"""scripts/count_states.py must count exactly the states explore() reaches."""

import importlib.util
from pathlib import Path

import pytest

from analint.validator.engine import build_spec
from analint.validator.explorer import build_canonical_initials, explore

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("count_states", ROOT / "scripts/count_states.py")
assert _spec is not None and _spec.loader is not None
count_states = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(count_states)


@pytest.mark.parametrize("example", ["broker", "k8s_replicaset", "coin", "mafia"])
def test_count_matches_explore(example):
    path = ROOT / "examples" / example
    spec, _, _ = build_spec(path)
    assert spec is not None
    initials, _ = build_canonical_initials(spec)
    exp = explore(spec, initials, 1_000_000)
    assert not exp.capped
    assert count_states.count_states(path)["states"] == len(exp.states)


def test_violating_states_are_counted_but_not_expanded(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Add, Entity, Field, Invariant, Spec\n"
        "class Box(Entity):\n"
        "    n: int = Field(0, ge=0, le=3)\n"
        "tick = Action(pre=[Box.n < 3], effect=[Add(Box.n, 1)])\n"
        "low = Invariant(Box.n <= 1)\n"
        "spec = Spec(id='s', name='s', actions=[tick], invariants=[low])\n"
    )
    spec, _, _ = build_spec(entry)
    assert spec is not None
    initials, _ = build_canonical_initials(spec)
    assert len(explore(spec, initials, 100).states) == 3  # n = 0, 1, 2 (illegal, kept)
    assert count_states.count_states(entry) == {"states": 3, "defects": 0, "illegal": 1}
