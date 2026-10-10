"""The compact state store (research/36 R4): a state is its key and its
context is rebuilt from it, so the codec must round-trip exactly — on real
explored states of every example, and through the >16-bit escape."""

from __future__ import annotations

from pathlib import Path

import pytest

from analint import Action, Entity, Field, Spec
from analint.validator import explorer as ex
from analint.validator.engine import prepare_model
from analint.validator.explorer import (
    build_canonical_initials,
    decode_state,
    explore,
    render_state,
    state_key,
)
from analint.validator.kernel import Outcome, step

EXAMPLES = Path(__file__).parent.parent / "examples"
EXAMPLE_DIRS = sorted(p.name for p in EXAMPLES.iterdir() if (p / "spec.py").exists())


@pytest.mark.parametrize("name", EXAMPLE_DIRS)
def test_explored_states_round_trip(name):
    spec = prepare_model(EXAMPLES / name).spec
    initials, _ = build_canonical_initials(spec)
    if initials is None:
        pytest.skip("no canonical initial state")
    exp = explore(spec, initials, 300)
    checked = 0
    for key in exp.order:
        ctx = decode_state(key)
        assert state_key(ctx) == key
        # a successor computed from the rebuilt context encodes and decodes
        # back to the same rendered state
        for action in spec.actions:
            result = step(spec, action, ctx, explain=False)
            if result.outcome is Outcome.ACCEPTED and result.post_context is not None:
                post = result.post_context
                assert render_state(decode_state(state_key(post))) == render_state(post)
                checked += 1
    assert len(exp.states) > 0 and (checked > 0 or not spec.actions)


def test_codes_past_sixteen_bits_round_trip():
    class Dial(Entity):
        n: int = Field(0, ge=0, le=9)

    spec = Spec(id="d", name="d", entities=[Dial], actions=[Action(id="noop")])
    ctx = {Dial: Dial(n=3)}
    layout_id, _ = ex._state_layout(tuple(ctx))
    # pretend 70,000 value tuples were seen: the next code needs the escape
    ex._SLOT_VALUES[layout_id][0].extend([None] * 70_000)
    try:
        fresh = {Dial: Dial(n=7)}
        key = state_key(fresh)
        assert ex._ESCAPE in memoryview(key).cast("H")
        assert render_state(decode_state(key)) == render_state(fresh)
        assert state_key(decode_state(key)) == key
    finally:
        assert spec.entities  # keep the spec alive while the layout is patched
