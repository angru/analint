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
