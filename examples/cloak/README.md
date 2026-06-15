# cloak — Cloak of Darkness (interactive-fiction benchmark)

## Purpose & source
The canonical "Cloak of Darkness" IF benchmark (Roger Firth, 1999), modelled as a
checkable analint spec (research/06). A small reachability puzzle with a subtle
win/lose condition.

## Modeled scope & omissions
Three rooms (Foyer, Cloakroom, Bar). The velvet cloak darkens the Bar while worn;
acting in the dark tramples the sawdust message. Hanging the cloak on the hook
lights the Bar. Win if the message was trampled at most once. Only the puzzle
state is modelled — no parser, no free-text.

## Key entities / actions / properties
- `Room`, `Player`, `Hook`, `Message`, `Game` (Result).
- `win_is_reachable` / `lose_is_reachable` (Reachable), `game_can_always_end`,
  `every_action_playable`, and an invariant that the cloak can never be on the hook
  and on the player at once.

## Run
```
uv run analint check examples/cloak
```

## Expected outcome
PASS, exit 0, no warnings.

## What a behavioural change means
If a change makes `win_is_reachable` or `lose_is_reachable` fail, an ending became
unreachable; if the cloak invariant fails, an action moved the cloak inconsistently.

## Related research
research/06 (interactive-fiction case study).
