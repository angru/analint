# coin — Quint "coin" tutorial (DELIBERATELY RED)

## Purpose & source
A translation of Quint's flagship `coin.qnt` tutorial (Informal Systems), itself a
model of the Solidity subcurrency example (research/15). Kept as a side-by-side
comparison with Quint.

## Modeled scope & omissions
A bounded `Account` scope (alice/bob/eve), a minter, and `send` between holders.
Balances are range-checked (0..5); the total supply is a `Sum` aggregate. Domains
are small and finite so the engine explores explicitly.

## Key entities / actions / properties
- `Account` scope, `mint` (minter only), `send` (parameterised over accounts/amount).
- `balances_stay_in_range`, `everyone_can_get_paid`, `every_method_callable`, and the
  teaching property `supply_never_overflows`.

## Run
```
uv run analint check examples/coin
```

## Expected outcome
**FAIL, exit 1 — on purpose.** `supply_never_overflows` fails with a counterexample
trace: every individual balance is range-checked, but nothing bounds their sum, so
the total can overflow. This is exactly the violation the Quint lesson demonstrates.

## What a behavioural change means
This example must stay red. If `supply_never_overflows` starts passing, the bug it
teaches was silently fixed/hidden — investigate before updating the manifest.

## Related research
research/15 (Quint comparison).
