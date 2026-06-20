# ecommerce — a small order/checkout domain

## Purpose & source
A compact, invented e-commerce domain (no external source) exercising entities,
a lifecycle, an event with payload, and reachability.

## Modeled scope & omissions
`Order` (PENDING → PAID | CANCELLED), a `Wallet`, a `Product`, and a `checkout`
that emits an `OrderPlaced` event. Payments/refunds beyond the wallet balance and
multi-item carts are out of scope.

## Key entities / actions / properties
- `Order`, `Wallet`, `Product`; `OrderPlaced` event.
- `checkout` (emits `OrderPlaced`), cancel/pay actions; `paid_is_reachable` (Reachable).

## Run
```
uv run analint check examples/ecommerce
```

## Expected outcome
PASS, exit 0, with no warnings.

## What a behavioural change means
A new FAIL in `paid_is_reachable` would mean the happy path became unreachable.

## Related research
research/30 (subtractive public-API cleanup).
