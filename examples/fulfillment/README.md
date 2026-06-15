# fulfillment — an order-fulfillment saga

## Purpose & source
An invented but realistic distributed saga (no external source): reservation,
payment, shipment, and a compensation for every failure — verified to never wedge.

## Modeled scope & omissions
The saga state machine and its compensations only; no real queues, timeouts or
retries (those are temporal/at-least-once concerns outside bounded reachability).
The model is composed from `queries` and `scenarios` modules via the entry point.

## Key entities / actions / properties
- Saga steps with success/failure branches and compensations.
- `saga_always_settles`, `no_money_for_nothing`, `no_free_goods`, `refund_path_exists`,
  `happy_path_exists`, `every_step_used`, and an invariant that a delivered order is
  always a captured payment.

## Run
```
uv run analint check examples/fulfillment
```

## Expected outcome
PASS, exit 0, no warnings.

## What a behavioural change means
If `saga_always_settles` fails, some interleaving wedges (a state with no path to a
terminal settlement); if `no_money_for_nothing` / `no_free_goods` fail, a
compensation gap was introduced.

## Related research
research/12 (domain layer / DDD).
