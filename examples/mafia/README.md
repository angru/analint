# mafia — Mafia / Werewolf (from Quint)

## Purpose & source
A translation of Quint's `play_mafia.qnt` (research/16). Demonstrates verifying a
property under EVERY nondeterministic initial role assignment, not one convenient one.

## Modeled scope & omissions
Three fixed player entities (Mahtab, Gabriela, Max) with a night-first 3-player game.
The role assignment is NOT fixed: queries quantify over a declarative `Initial`
relation, and actions are role-generic `Param` families that never name the mafia.

## Key entities / actions / properties
- `Mahtab`/`Gabriela`/`Max`, `Game` (Role/Phase/GameStatus).
- Headline: `citizens_cannot_win` (Unreachable under all role assignments),
  `mafia_can_win` (Reachable), `status_is_always_correct`, and an invariant tying
  game status to the surviving roles.

## Run
```
uv run analint check examples/mafia
```

## Expected outcome
PASS, exit 0, no warnings.

## What a behavioural change means
If `citizens_cannot_win` becomes reachable, some rule change handed the citizens a
winning line; if `mafia_can_win` fails, the mafia path was broken.

## Related research
research/16 (nondeterministic initial states), research/15 (Quint comparison).
