# sunless_crypt — a playable dungeon crawl (checkable AND runnable)

## Purpose & source
An experiment (research/21): a model authored purely for *checking* that is also
*executed* as a real text game by the generic runner in `examples/play.py`, with no
framework changes. No external source.

## Modeled scope & omissions
A small gamebook dungeon: torch → light it → sword → crypt → slay the guardian →
key → vault → amulet → altar to escape. Fighting unarmed and stumbling in the dark
drain stamina; at zero the hero dies. Only the game state is modelled.

## Key entities / actions / properties
- `Room`, `Hero`, `Crypt`, `Game` (Result); many room-transition and item actions.
- `win_is_reachable`, `death_is_reachable`, `no_softlock`, `stamina_never_negative`,
  `every_action_playable`.

## Run
```
uv run analint check examples/sunless_crypt          # check it
uv run python examples/play.py sunless_crypt         # play it
```

## Expected outcome
PASS, exit 0, with **13 intentional `has no scenarios` warnings** (one per action with
no dedicated scenario). The reachability queries cover behaviour exhaustively, so the
missing per-action scenarios are an accepted coverage trade-off, not a defect.

## What a behavioural change means
If `no_softlock` fails, a state became a dead end with no path to an ending; if
`win_is_reachable` fails, the critical path was broken.

## Related research
research/21 (playable-spec experiment).
