"""A generic text-adventure runner for ANY analint spec.

    uv run python examples/play.py sunless_crypt
    uv run python examples/play.py sunless_crypt --choices 1,3,2,...   # scripted

The framework describes and checks systems; it does not ship an executor. This
script lives entirely in the examples folder and treats analint as a library: it
reads the model (entities, actions, lifecycles) and drives it through the **same
transition kernel the checker uses** — ``analint.validator.kernel.step`` — so a
played move can never diverge from scenario/flow/explorer semantics. An action is
offered as a choice exactly when ``step`` ACCEPTS it; the move's next state is the
kernel's ``post_context``.

Scope: the runner enforces *transition legality* only (preconditions, effects,
field bounds, lifecycle transitions and postconditions, all via ``step``). It does
NOT additionally assert world ``Invariant``s — those are verified separately by
``analint check``. So "playable" means "every move is a legal transition", and the
invariants are someone else's (the checker's) job.

Mechanics come entirely from the model. Prose does not: the game module supplies
``describe(ctx)`` / ``INTRO`` / ``ENDINGS`` as ordinary Python beside the spec.
A module may also set ``AUTO`` — ids of actions the runner fires automatically
when enabled (forced transitions like death), and label choices via ``Action.name``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analint.validator.engine import build_spec
from analint.validator.explorer import build_initial
from analint.validator.kernel import Outcome, step

EXAMPLES = Path(__file__).parent


def _load_game(name: str):
    """Load through the framework loader so action ids are filled and params
    expanded; return (spec, narration_module) sharing one set of Entity classes."""
    spec, modules, errors = build_spec(EXAMPLES / name)
    if spec is None:
        sys.exit(f"cannot load {name}: {errors}")
    module = next((m for m in modules if hasattr(m, "describe")), None)
    if module is None:
        sys.exit(f"{name}/spec.py has no describe(ctx) narration function")
    return spec, module


def _try(spec, action, ctx: dict) -> dict | None:
    """Return the next state if the kernel ACCEPTS this transition, else None."""
    result = step(spec, action, ctx)
    if result.outcome is Outcome.ACCEPTED:
        return result.post_context
    return None


def _ending(spec, ctx: dict):
    """Return the terminal lifecycle value if the game is over, else None."""
    for lc in spec.lifecycles:
        inst = ctx.get(lc.entity_cls)
        value = getattr(inst, lc.field_name, None) if inst is not None else None
        if value in lc.terminal:
            return value
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Play an analint spec as a text game.")
    parser.add_argument("game", help="example directory name, e.g. sunless_crypt")
    parser.add_argument("--choices", help="comma-separated 1-based choices (non-interactive)")
    args = parser.parse_args()

    spec, game = _load_game(args.game)
    auto = set(getattr(game, "AUTO", set()))
    endings = getattr(game, "ENDINGS", {})

    ctx, error = build_initial(spec, [])
    if ctx is None:
        sys.exit(f"cannot start: {error}")

    scripted = [int(c) for c in args.choices.split(",")] if args.choices else None
    print(getattr(game, "INTRO", ""))

    while True:
        # forced transitions (e.g. death) fire before the player is asked
        fired_auto = True
        while fired_auto:
            fired_auto = False
            for action in spec.actions:
                if action.id in auto:
                    post = _try(spec, action, ctx)
                    if post is not None:
                        ctx = post
                        fired_auto = True

        end = _ending(spec, ctx)
        if end is not None:
            print("\n" + endings.get(end, f"THE END ({end})."))
            return

        print("\n" + game.describe(ctx))
        choices = [
            (a, post)
            for a in spec.actions
            if a.id not in auto and (post := _try(spec, a, ctx)) is not None
        ]
        if not choices:
            print("\nThere is nothing you can do. (softlock)")
            return
        for i, (action, _post) in enumerate(choices, 1):
            print(f"  {i}. {action.name or action.id}")

        if scripted is not None:
            if not scripted:
                print("\n(end of script)")
                return
            pick = scripted.pop(0)
            print(f"> {pick}")
        else:
            try:
                pick = int(input("> ").strip())
            except ValueError, EOFError:  # PEP 758 (Python 3.14): parens optional
                print("\n(quit)")
                return
        if not 1 <= pick <= len(choices):
            print("no such choice")
            continue
        ctx = choices[pick - 1][1]


if __name__ == "__main__":
    main()
