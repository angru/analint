"""Smoke test for the playable-spec runner, examples/play.py (P4.0c, research/26).

The runner drives a spec through the unified ``kernel.step`` and must keep working
(it once broke on a private import). This loads sunless_crypt through the runner's
own helpers and replays the documented winning path action-by-action, asserting
every move is ACCEPTED by the kernel and the game reaches its escape ending. A
failure here means the playable example drifted from the engine's transition
semantics — exactly what the kernel unification is meant to prevent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from analint.validator.explorer import build_initial

PLAY = Path(__file__).parent.parent / "examples" / "play.py"

# The winning witness for sunless_crypt (the trace of win_is_reachable).
WIN_PATH = [
    "enter_hall",
    "enter_armory",
    "take_sword",
    "leave_armory",
    "enter_crypt_dark",
    "slay_guardian",
    "take_key",
    "unlock_vault",
    "enter_vault",
    "take_amulet",
    "leave_vault",
    "leave_crypt",
    "enter_altar",
    "place_amulet",
]


def _load_play():
    spec = importlib.util.spec_from_file_location("examples_play", PLAY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_play_runner_drives_sunless_crypt_to_victory():
    play = _load_play()
    spec, game = play._load_game("sunless_crypt")
    ctx, error = build_initial(spec, [])
    assert ctx is not None, error

    by_id = {action.id: action for action in spec.actions}
    auto = set(getattr(game, "AUTO", set()))

    def fire_auto(ctx: dict) -> dict:
        fired = True
        while fired:
            fired = False
            for action in spec.actions:
                if action.id in auto and (post := play._try(spec, action, ctx)) is not None:
                    ctx, fired = post, True
        return ctx

    ctx = fire_auto(ctx)
    for action_id in WIN_PATH:
        post = play._try(spec, by_id[action_id], ctx)
        assert post is not None, f"kernel.step did not ACCEPT '{action_id}' on the winning path"
        ctx = fire_auto(post)

    assert play._ending(spec, ctx) == "escaped", "the documented winning path did not escape"
