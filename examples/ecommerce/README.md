# ecommerce — a small order/checkout domain

## Purpose & source
A compact, invented e-commerce domain (no external source) exercising entities,
actors, a lifecycle, an event with payload, and reachability.

## Modeled scope & omissions
`Order` (PENDING → PAID | CANCELLED), a `Wallet`, a `Product`, and a `checkout`
that emits an `OrderPlaced` event. Payments/refunds beyond the wallet balance and
multi-item carts are out of scope.

## Key entities / actions / properties
- `Customer`/`Admin` actors; `Order`, `Wallet`, `Product`; `OrderPlaced` event.
- `checkout` (emits `OrderPlaced`), cancel/pay actions; `paid_is_reachable` (Reachable).

## Run
```
uv run analint check examples/ecommerce
```

## Expected outcome
PASS, exit 0, with one intentional structural **warning** at `action:checkout`:
`OrderPlaced` is emitted but no action lists it in `on=` (no documented handler).
`on` is documentary metadata, so this is a warning, not an error.

## What a behavioural change means
Adding an action with `on=[OrderPlaced]` would clear the warning. A new FAIL in
`paid_is_reachable` would mean the happy path became unreachable.

## Related research
research/14 (declarativity / `on` as documentary metadata).
