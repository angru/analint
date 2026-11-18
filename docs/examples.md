# Examples gallery

Clone the repository to run these models; the Python package installation does
not place the examples in your working directory:

```bash
git clone https://github.com/angru/analint
cd analint
uv sync --frozen
uv run analint check examples/cloak/
```

Each example has a README describing its assumptions and intended result.
`examples/expectations.toml` records verdicts separately from the detailed
regression snapshots. A deliberately failing model is a successful demonstration
when it exposes the documented defect.

## Start here

| Example | What to learn | Intended verdict |
| --- | --- | --- |
| [E-commerce](https://github.com/angru/analint/blob/main/examples/ecommerce/README.md) | Single-file actions, constraints, scenarios and payload templates | PASS |
| [Taskboard](https://github.com/angru/analint/blob/main/examples/taskboard/README.md) | Multi-file composition, explicit contracts and terminal lifecycles | PASS |
| [Cloak of Darkness](https://github.com/angru/analint/blob/main/examples/cloak/README.md) | A game walkthrough found through reachability; recoverability through NoDeadEnd | PASS |
| [Trollbridge](https://github.com/angru/analint/blob/main/examples/trollbridge/README.md) | All scenarios pass, but exploration finds a softlock and negative health | **FAIL, deliberate** |

## Larger models and domain evidence

| Example | What to learn | Intended verdict |
| --- | --- | --- |
| [Fulfillment](https://github.com/angru/analint/blob/main/examples/fulfillment/README.md) | State-chained order saga with compensations and reachable settlement | PASS |
| [Branch protection](https://github.com/angru/analint/blob/main/examples/branch_protection/README.md) | A finite model of GitHub protected-branch policy and requirement changes | PASS |
| [OAuth](https://github.com/angru/analint/blob/main/examples/oauth/README.md) | Scoped clients, token provenance, replay revocation and a Quint comparison | PASS |
| [Kubernetes ReplicaSet](https://github.com/angru/analint/blob/main/examples/k8s_replicaset/README.md) | Bounded Pods, quota, presence, aggregates and ownership provenance | PASS |
| [Broker](https://github.com/angru/analint/blob/main/examples/broker/README.md) | Verification, accounts and payments composed from contracts; property slicing | PASS |

## Fulfillment requirement-change trial (unreleased)

This repository-example trial exercises [check selection](cli.md#selecting-checks-over-one-model-unreleased)
with one shared model. The baseline customer cancellation window closes at payment
capture. The additive hypothesis permits cancellation while the shipment is
in transit, with cancellation and refund in one atomic model action. Cancellation
after delivery is rejected. The original pre-dispatch cancellation policy remains.

Run from the repository checkout:

```bash
uv run python scripts/trial_fulfillment.py --output /tmp/fulfillment-trial
uv run analint check examples/fulfillment \
  --what-if benchmarks/fulfillment_cancellation.py \
  --check flow:cancel_in_transit --check query:no_money_for_nothing \
  --max-states 20000 -f json
```

The runner leaves the baseline example unchanged. It saves the baseline inspection,
exact before/after/control hypotheses, full and compact reports, CLI exit codes,
witnesses with state changes, and a source-hashed summary under `--output`.
The extended model is an additive what-if revision, not a new root for each flow.
Within each revision, all selections reuse the same prepared `Spec`; the runner
checks membership identity and unchanged declarations. Every original action is
retained, including delivery, loss and compensations.

| Model revision | Full check | Selected flows | Selected payment safety | States per property |
| --- | --- | --- | --- | --- |
| Baseline | PASS | No flows declared | PASS in full run | 34 |
| Old model plus new requirement probes | FAIL | Cancellation fails; delivery passes | PASS | 34 |
| Cancellation with atomic refund | PASS | PASS separately and together | PASS | 36 |
| Above plus an alternative cancellation without refund | FAIL | PASS separately and together | FAIL | 38 |

The old-model probe fails because the new journey is blocked, not because the old
model is inconsistent. The negative control adds `cancel_without_refund` outside
both flows. Property exploration finds it after
`supplier_restock → reserve_stock → authorize_payment → confirm_order →
capture_payment → dispatch → cancel_without_refund`. The order is cancelled while
payment stays captured; `settlement_always_reachable` also fails because no recovery
is possible. Both explicit flows still pass: their coverage is `executed_steps_only`.
The control intentionally has one `structural.no_scenarios` warning; that warning
is retained and is not the cause of the non-strict FAIL.

All 44 cases agree between sliced and whole-model verification at a 20,000-state
budget. CLI/library results, check/trace action paths, and cold/warm cache reports
also agree (excluding timings and the requested cache-option metadata). The
passing selected safety proof needs no supporting invariant; the failing control
falls back to the constrained path with `delivered_means_paid` as support. No
query is INCONCLUSIVE and no original action is removed.

The model is coupled: selection still explores 36 states in the passing revision.
One local Python 3.14 run took about 4.3 ms for full validation, 4.0 ms for the safety
selection, and 1 ms per individual flow, excluding preparation. These are single
observations, not a speedup claim. Compact output was slightly larger on these
small reports. See the committed
[measurement record](https://github.com/angru/analint/blob/main/benchmarks/fulfillment-trial-results.json)
for source hashes and all measurements.

**Bounds:** one order, one payment, one shipment and a warehouse capacity of two.
Refund is atomic with cancellation; payment-provider latency, physical returns,
continued carrier activity after cancellation, retries and concurrent orders are
outside the model. `NoDeadEnd` establishes reachable settlement, not eventual
completion. This is an invented repository example and does not close the external
real-spec trial or establish production conformance. No engine change or new DSL
primitive was needed.

## Games and comparison models

| Example | What to learn | Intended verdict |
| --- | --- | --- |
| [Coin](https://github.com/angru/analint/blob/main/examples/coin/README.md) | Quint tutorial translated into the DSL; reproduces a supply-overflow counterexample | **FAIL, deliberate** |
| [Mafia](https://github.com/angru/analint/blob/main/examples/mafia/README.md) | Declarative initial role assignments, finite quantifiers and parameterized actions | PASS |
| [Sunless Crypt](https://github.com/angru/analint/blob/main/examples/sunless_crypt/README.md) | One model both verified and played using the example runner | PASS |

PASS describes the declared finite abstraction. It does not claim that a real
OAuth deployment, Kubernetes cluster or broker implementation has been verified.
Read each model's assumptions before reusing its properties.

## Scaling benchmarks

`benchmarks/broker/m4.py`, `m5.py` and `m6.py` extend the broker baseline with risk,
partner restrictions and bounded multiplicity. They are experimental benchmark
entries, separate from the example-intent gallery. Their composed explorations
can exhaust their budget and remain INCONCLUSIVE; executable fixture scenarios
do not replace a complete canonical proof. See the
[broker benchmark notes](https://github.com/angru/analint/blob/main/examples/broker/README.md)
for bounds, measurements and the separate settlement abstractions.

The [verification concepts](concepts.md) explain how to distinguish a
counterexample, an expected rejection and an unfinished exploration.
