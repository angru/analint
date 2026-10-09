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

## Run
```bash
uv run analint check examples/broker            # all PASS
uv run analint check examples/broker --no-slice  # same verdicts, whole model per check
uv run analint show -p examples/broker
uv run analint affects Client.tier -p examples/broker
```
