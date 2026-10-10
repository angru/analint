# broker — a generic retail broker (scaling benchmark)

## Purpose & source
The scaling benchmark of research/34: a realistic business system made of
several **mostly independent processes** (client verification, trading
accounts, payments) coupled by a few hub facts (verification tier, region,
client status). It is a **neutral composite of common retail-broker practice**:
no particular provider is described or cited, and every number is an
illustrative modelling bound. It also dogfoods explicit composition
(research/35): one `Contract` per process, composed by the root `Spec`.

## Processes (one contract each)
- **`profile`** (`profile.py`, increment M1): contacts → personal details →
  economic profile, then an identity document and a proof of address. Each
  review may reject (resubmit) or, after `DOC_ATTEMPTS` failures, lock the
  document until support reopens it. Each level raises the deposit tier.
  One-time security codes.
- **`trading_accounts`** (`accounts.py`, M2): open an account (class × mode;
  no demo for the cent class), archive/restore, compliance disable/support
  reactivation, deletion of an inactive demo account, positions (real
  positions need 1 unit of margin; trading-gated regions need full
  verification).
- **`payments`** (`payments.py`, M3): deposits within the tier's cumulative
  limit, card eligibility for payouts, withdrawals (fresh security code, free
  margin, cannot be cancelled: paid out or rejected and refunded), closing the
  profile only with no money left.

## Properties
| Id | Property | How |
|---|---|---|
| P1 | deposits never exceed the tier limit | `deposits_within_tier_limit` invariant |
| P2 | a withdrawal never takes an open position's margin | `margin_stays_covered` invariant |
| P3 | archived/disabled accounts never trade or move money | `post` on money/trading actions + negative scenarios |
| P7 | verification never gets stuck (support reopens a lock) | `verification_never_stuck` NoDeadEnd |
| P8 | a withdrawal needs a fresh security code | guard + `sc_withdrawal_without_code_is_rejected` |
| P11 | every action is usable | `every_action_is_usable` DeadActions |
| P12 | no cent-class demo account | `no_cent_demo` Unreachable |
| — | the stored tier agrees with the documents | four `profile` invariants |
| — | money is conserved | `money_is_conserved` (deposited = balances + in flight + paid) |

42 scenarios (positive and `Expect.FAIL`) and an onboarding flow document each
action.

## Assumptions (where common practice is silent)
Money is a few abstract units (`MONEY_CAP`); equity, prices and P&L are not
modelled yet (increment M4). A withdrawal is `requested → none`, either paid or
refunded. Archiving requires no open position and no payout in flight. Region
is fixed per client (an initial relation over three regions). One account slot
(multiplicity is increment M6).

## Measured change series (research/34 §8)
| Increment | actions | whole-model states | verification slice | money slice | `check` sliced / `--no-slice` |
|---|---:|---:|---|---|---|
| M1 profile | 15 | 132 | 22 states | — | ~0.01 s / 0.01 s |
| M2 + accounts | 27 | 1,770 | 22 states | — | 0.09 s / 0.25 s |
| M3 + payments | 33 | 15,912 | 22 states | 15,912 (whole) | 2.7 s / 3.3 s |

Verification properties stay on a 22-state slice however the model grows. The
money properties read the tier, account status and security code, so their
slice is the whole coupled model; it needs ~16k states, so the spec declares
`max_states = BUDGET` (50k) instead of the 10k default.

## Quint port (research/34 §7–§8 D)
`broker.qnt` encodes the same abstraction, choosing the increment with
`--step=stepM1|stepM2|stepM3`. TLC finds exactly the same number of distinct
states as analint at every increment (132 / 1,770 / 15,912). NoDeadEnd and
DeadActions have no Quint form; 11 of the scenarios are ported as `run` tests.

```bash
quint typecheck examples/broker/broker.qnt
quint test examples/broker/broker.qnt --main=broker
quint verify examples/broker/broker.qnt --main=broker --backend=tlc \
  --step=stepM3 --invariant=allInvariants          # needs Java (OpenJDK 17)
```

## Run
```bash
uv run analint check examples/broker            # all PASS
uv run analint check examples/broker --no-slice  # same verdicts, whole model per check
uv run analint show -p examples/broker
uv run analint affects Client.tier -p examples/broker
```

## M4 risk extension (2026-10-10)

The measured M1–M3 example and Quint port stay at their original abstraction.
`benchmarks/broker/m4.py` composes those contracts with a risk contract. It has
7 entity types, 93 expanded actions, 58 scenarios and two executable flows.

The risk contract adds four equity buckets, equity/history eligibility for
uncapped leverage, a temporary effective cap during high-margin periods,
margin-call/stop-out buckets, least-profitable-order-first liquidation, and
negative-balance protection only after a full stop out. A cent account reaches
stop out at zero equity; other classes may remain in margin call. A period starts
after the service has lowered all effective caps; uncapped *selection* can
persist while the effective cap is low (P10).

The two-slot risk and order universes are fixed. M4 permits only one concurrent
risk account and one open order; the other slot is an alternative identity, not
an extra concurrent account. Closed order slots are reclaimable. Risk equity is
an external settlement bucket, not another cash amount: this model does not
reconcile P&L or recapitalization with the separate M3 ledger. That boundary is
deliberate and must be considered when interpreting dependency cones.

```bash
uv run analint check benchmarks/broker/m4.py --max-states 2000
```

The composed verification is expected to be **INCONCLUSIVE** at this budget.
Scenarios and flows execute successfully; they demonstrate the declared
transitions but do not prove safety over every composed reachable state.
The four KYC invariants still prove on 22-state slices. The risk and money cones
exhaust the budget. No check is permanently `NOT_CHECKED` because a reserved
slot is absent: M4 exposed and regression-tested that applicability bug.

### Quint cross-check of M4 (2026-10-10)

`benchmarks/broker/risk.qnt` ports the risk contract on top of `broker.qnt`.
The risk increment alone (`benchmarks/broker/m4_risk.py`: client registered,
active and unchanged) has **54,084** distinct states in both analint and TLC,
and its four invariants pass in both; a planted defect yields the same
six-action counterexample. At M6 capacity (`m6_risk.py`, two concurrent
accounts and orders) both count **4,440,789** states (analint via
`scripts/count_states.py`). Full M4 exceeds a million states in analint; TLC
finishes it: **286,428,912** states, all M3 and risk invariants hold (2 h 16 min;
research/34 §8 B2).

```bash
uv run analint check benchmarks/broker/m4_risk.py
quint verify benchmarks/broker/risk.qnt --main=risk --backend=tlc \
  --init=initRiskOnly --step=stepRiskOnly --invariant=riskInvariants
```

## M5 partners (2026-10-10)

`benchmarks/broker/m5.py` adds partner status, referral attribution and a reward
wallet: 10 entity types, 105 actions and 72 scenarios. The capability matrix is
an illustrative policy, not a claim about a specific provider:

| Status | New attribution | New commission | Accrued withdrawal |
|---|---|---|---|
| active | yes | yes | yes |
| link blocked | no | yes | yes |
| on hold | yes | no | no |
| blocked (irreversible) | no | no | yes |

Partner changes and withdrawals consume a fresh client security code.
Withdrawal assumes an active client; the partner's terminal lock does not freeze
the separate reward wallet. Commission is one award of one or two abstract units
depending on level, conserved between accrued and paid totals. Qualification is
an environment flag; promotion and automatic downgrade act on it. Historical
attribution and rewards remain after blocking. Negative scenarios check that
blocking prevents *new* attribution and rewards.

The shared security code couples this process to cash payments. At the same 2k
budget, the four KYC invariants still prove locally; composed reward, payment
and risk checks remain inconclusive. Scenario success is not a complete proof.

## M6 multiplicity and measurements (2026-10-10)

`benchmarks/broker/m6.py` raises the capacities to two concurrent risk accounts
and open orders, and adds two payment-method slots. It has 12 entity types,
129 expanded actions, 86 scenarios and two flows. Scenarios distinguish the
worst order from a better one, reject protection after a partial stop, and
show that another account's losses do not determine the local liquidation order.

Payment methods require ownership and currency agreement for funding/payouts.
Funding makes a method eligible; requesting a payout consumes a fresh code and
holds funds. Settlement pays them, rejection refunds them, and no cancellation
transition exists. A separate two-unit settlement ledger conserves these rails'
funds. As with risk equity and partner commissions, it is not folded into the
M3 cash ledger: P1 and profile-termination money checks still cover M3 cash only.
Consolidated P&L, all-balance termination and multiple M3 cash accounts remain
modelling follow-ups, not guarantees of this benchmark.

Run the reproducible harness from the repository:

```bash
uv run python scripts/bench_broker.py --max-states 2000 --repeats 2 --json
uv run python scripts/bench_broker.py --max-states 10000 --repeats 2 --memory --json
uv run analint check benchmarks/broker/m6.py --max-states 10000 --no-slice
```

The harness overrides **every** query and canonical budget equally; imported
M1–M3 queries otherwise retain their 50k budgets. It records per-check verdicts,
states, timings and cone fields, source/engine digests, Python/platform and peak
traced memory in a separate run. Import closures are preloaded. Timings are
informational; comparisons are within one runner and repeat count. Full records
live in `benchmarks/broker/results-10000.json`.
The corresponding 2k runs are in `benchmarks/broker/results-2000.json`.

Measurement (macOS arm64, CPython 3.14.5, median of two runs, no profiling
during timing; idle machine). Engine of 2026-10-10 after the compact state
keys and compiled predicates; the first measurement (revision bae44d0) is in
parentheses. Every verdict, summary and per-check state count is identical
between the two.

| Increment | actions | 2k budget sliced / whole | 10k budget sliced / whole | peak MiB at 10k sliced / whole | KYC invariants |
|---|---:|---|---|---|---|
| M4 | 93 | 0.55 / 0.25 s (0.98 / 0.37) | 3.10 / 1.27 s (6.36 / 2.04) | 68 / 16 (291 / 70) | 4 PASS on 22 states |
| M5 | 105 | 0.53 / 0.26 s (0.98 / 0.38) | 2.91 / 1.24 s (6.08 / 2.01) | 80 / 18 (329 / 73) | 4 PASS on 22 states |
| M6 | 129 | 0.60 / 0.30 s (1.08 / 0.46) | 3.15 / 1.49 s (6.52 / 2.35) | 85 / 20 (391 / 91) | 4 PASS on 22 states |

**All six composed runs are INCONCLUSIVE.** Whole-model verification proves
none of the KYC invariants before the cap; slicing proves all four, but spends
more time exploring distinct genuinely coupled cones. The other invariants
remain capped, with no FAIL or NOT_CHECKED results at these budgets. At 10k,
M4/M5 find some existential witnesses; M6's new multiplicity/risk witnesses are
not established by the capped canonical search. Its scenarios/flows are
executable fixture witnesses, not a canonical reachability proof.

The implication for P5 E is limited: slicing retains exact local proofs, but
does not make this coupled model fully tractable. These capped measurements
do not give the total state-space size or justify a native/export backend yet.
First measure the distinct large cones at larger budgets on a controlled runner,
and resolve the modelling boundaries above before drawing a product decision.
Peak traced allocations reached 391 MiB for M6 with multiple capped slices
versus 91 MiB for one capped whole-model exploration (85 / 20 MiB after the
compact state keys). This motivates profiling retained
graphs/state storage (R4); it does not prove that a compact store can finish the
unexplored state product.
