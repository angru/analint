# trollbridge — a deliberately broken micro-RPG (DELIBERATELY RED)

## Purpose & source
A teaching example (research/06 family): the scenarios all pass, but the model hides
a softlock and a death the author forgot to model. Example-based tests miss bugs
nobody thought to test; the reachability queries find both, with traces.

## Modeled scope & omissions
A hero (10 HP, 6 gold), a shop (sword 5 gold, potion 3 gold/+4 HP), a troll (slain
only with the sword, 3 HP) and a ruined bridge (crossing costs 8 HP). Only the
micro-economy and the bridge are modelled.

## Key entities / actions / properties
- `Hero`, `Troll`, `Quest`; buy/drink/fight/cross actions.
- `bridge_is_reachable`, `every_action_playable`, `no_gold_from_thin_air`, plus the
  two properties that catch the bugs: `hp_never_negative` and `no_softlock`.

## Run
```
uv run analint check examples/trollbridge
```

## Expected outcome
**FAIL, exit 1 — on purpose.** `hp_never_negative` fails (the unmodelled bridge death
drives HP below zero) and `no_softlock` fails (the economy can wedge). Both come with
counterexample traces.

## What a behavioural change means
This example must stay red until the bugs are intentionally fixed. If either query
starts passing, confirm the fix was deliberate before updating the manifest.

## Related research
research/06 (case study), research/04 (reachability engine).
