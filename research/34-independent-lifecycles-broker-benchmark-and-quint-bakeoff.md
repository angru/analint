# 34 — Independent lifecycles: issue #3 diagnosis, a broker benchmark, and a Quint bake-off

**Date:** 2026-10-09
**Status:** proposal; awaiting review before any engine change
**Trigger:** [angru/analint#3](https://github.com/angru/analint/issues/3) — a
private spec (8 entities, 7 lifecycles, 64 expanded actions, 5
invariants, 7 queries) took 62.8 s, and 3 of its 7 queries came back
`INCONCLUSIVE` at the 10k-state budget. The issue lists all 5 invariants as
not checked (see §2.4).

## 1. Questions

1. Is this a design mistake in analint, or a missing engine capability?
2. Why would the same model be tractable in Quint, and is it really?
3. Should the owner of that spec switch to hand-written Quint?
4. What realistic, externally documented model should we use as the shared
   benchmark for analint and Quint, and in what order do we build it?

## 2. Measured diagnosis

### 2.1 Reproducer

A synthetic model with the issue's shape: `K` singleton entities, each with
one 5-state lifecycle (`A→B→C→D`, back-edges, terminal `E`) plus a boolean
flag. `B→C` requires the flag. 9 actions per entity. One invariant per entity
(`status == C ⇒ flag`) and three queries: one local `Reachable`, one
cross-entity `Reachable` (`E1 = D ∧ E2 = D`), and `DeadActions`. Each
component has 8 reachable local states, so the product is exactly `8^K`. The
same model was ported to Quint (Appendix A). Machine: macOS arm64, Python
3.14, Quint 0.32.0, OpenJDK 17.

### 2.2 Results

| Run | States | Wall time | Verdict |
|---|---:|---:|---|
| analint, K=7, default budget | 2 × 10,000 (capped) | 5.1 s | all 5 invariants `INCONCLUSIVE`; cross-entity `Reachable` `INCONCLUSIVE` |
| analint, K=5, budget 200k | 2 × 32,768 | 16.4 s | all `PASS` |
| analint `workflow_product(7)` (existing P4.4 family) | 16,384 | 4.3 s | 262 µs/state, ~12 KB/state |
| Quint → TLC, K=7 | 2,097,152 distinct (= 8^7) | 23 s wall / 146 s CPU | `[ok]` exhaustive |
| Quint → Apalache, bounded 10 steps | symbolic | 9.4 s | `[ok]` up to depth 10 |
| Quint → Apalache, inductive (`typeOK ∧ inv`) | symbolic | 4.8 s | `[ok]` for **all** depths |

TLC's distinct-state count equals the closed-form `8^7`, so both tools are
checking the same transition system; the comparison is apples to apples
(research/32's condition for any cross-tool timing statement).

Extrapolated from the measured per-state cost: the same K=7 space would take
analint ~9 minutes per exploration and ~25 GB of memory. The fixed 10k budget
therefore cannot help here, and raising it, as the issue says, only postpones
the cutoff.

### 2.3 Where the time goes (cProfile, K=7, default budget)

`check` explores the **same canonical space twice**: once in
`verify_invariants` and once for the default-source queries
(`explorer.py` `verify_invariants` calls `explore` directly and bypasses the
`run_query` cache; its docstring already notes this as a deferred
optimization). Within each exploration:

- 496,580 `kernel.step` calls for 2 × 10k states; only 93,944 (19%) accept.
- Every **rejected** guard builds a human message with `_describe(pred)`
  (805k `_describe_operand` calls), which the explorer immediately discards.
- `_collect_field_refs` re-walks each guard's AST on every call (1.6M
  `_operand_refs`), although the result is static per action.
- `exp.trace_to(key)` walks the parent chain on **every** `step` call
  (496k), but the trace is needed only to decorate a defect.
- Each accepted step copies every entity (`copy.copy` ×657k), computes
  `_state_diff` (artifact-only data), and `state_key` walks
  `all_fields` again (1.4M calls).
- The BFS queue is a `list` with `pop(0)`.

These are constant factors. The 3–10× they might buy together is an
estimate that phase A has to measure, and none of them changes the `8^K`
growth.

### 2.4 Reporting confusion

The issue says all 5 invariants were `NOT_CHECKED`. In the reproducer they
are `INCONCLUSIVE` (budget exhausted), yet the terminal summary prints
`invariants: 0 ok, 5 unchecked`, and JSON exposes only
`invariants_unchecked`, which merges `INCONCLUSIVE` and `NOT_CHECKED`
(`reporter/terminal.py`, `reporter/json_reporter.py`). An agent reading the
summary cannot tell "the budget ran out" from "the model could not be
built". That is a diagnostic defect, separate from performance.

### 2.5 Root cause: design or capability?

The DSL is not the problem. The model in the issue is a natural, idiomatic
analint spec. The problem is that the engine has **one** strategy for every
property:

> monolithic, whole-spec, explicit-state BFS from the canonical initial
> state, materialising every state as a dict of Python entity copies.

A product of independent lifecycles is the worst case for that strategy. A
property about one lifecycle pays for every other lifecycle's states and
interleavings. Earlier research listed symmetry and partial-order reduction
(research/19 §4, research/32), but it never listed the reduction that matters
most here: **property-directed slicing (cone of influence)**. This is the
real design gap. There is no property-local verification mode, so per-check
cost is global.

One semantic choice makes slicing slightly more subtle than in textbook model
checkers: a state that violates *any* invariant is not expanded, so
invariants act as global pruning. §5 shows that this is still compatible with
an exact slice.

## 3. Why Quint "works" here

- **TLC does not avoid the explosion.** It enumerated all 2.1M states:
  ~11 µs/state wall versus analint's ~250 µs (~23×), but ~70 µs of CPU time
  per state (~3.5×). Most of the gap is multi-core plus
  storing 64-bit fingerprints instead of whole states, so memory stays flat.
  At K=10 (~1.07 billion states) TLC is also hopeless.
- **Apalache avoids enumeration.** It encodes `k` steps symbolically in SMT,
  where independent components do not multiply. With an **inductive
  invariant** it proves the property for every depth in seconds, independent
  of K. The cost is human work: someone has to supply a type invariant and an
  inductive strengthening, and SMT is slow on arithmetic-heavy or
  quantifier-heavy models.
- Quint has no slicing either. Its advantage is backend engineering, not a
  better idea for this case.

Honest summary: for *this* workload Quint is ahead today because of
throughput (TLC) and symbolic proof (Apalache). After a cone-of-influence
slice, analint would check each property of the reproducer in a space of 8 or
64 states, i.e. milliseconds, exactly. Quint does not do that out of the box.

## 4. Fix options, ranked by value ÷ cost

| # | Option | Fixes issue #3? | Exactness | Cost |
|---|---|---|---|---|
| R1 | Constant-factor fixes (§2.3) + share the canonical exploration | no (3–10× faster) | unchanged | small |
| R2 | **Cone-of-influence slicing per property** | **yes**, for local and few-component properties | exact (§5) | medium |
| R3 | Reporting: separate `INCONCLUSIVE`/`NOT_CHECKED`; per-check time, states, slice, completeness; `--max-states` override | asked in the issue | n/a | small |
| R4 | Compact state store (tuple of slot values + fingerprint set; no per-state entity copies) | memory ↓ ~10× | unchanged | medium |
| R5 | Partial-order reduction (stubborn sets) for `Reachable`/`NoDeadEnd` within a large cone | partly | needs its own proof | high |
| R6 | External backend: emit Quint/TLA+ for TLC/Apalache | sidesteps | second semantics to keep aligned | high |

R1 + R3 are hygiene. R2 is the actual answer to the issue. R4 is for
cross-cutting properties whose cone really is large. R5 and R6 are gated on
benchmark evidence (§7).

## 5. Cone-of-influence slice — draft semantic contract

**Variables** are `(context key, field)` pairs, plus a per-slot `@present`
variable for scoped entities.

**Slice closure** for property `φ`. Start with `V = vars(φ)` and compute the
least fixpoint of:

1. An action is **relevant** if it writes any variable in `V` (Set, Add,
   Subtract, Create, Delete, including `Param` expansions).
2. For each relevant action, add to `V` **all** of its reads (`pre`, effect
   right-hand sides, `post`, emitted payload expressions), **all** of its
   writes, and the lifecycle field and `@present` of every entity it touches
   (the terminal lock and presence guards read them).
3. Add every invariant that mentions a variable in `V`, and add all of that
   invariant's variables to `V`.
4. Add the variables of `Initial.where` predicates that mention `V`. Slice
   roots are the **projection of the full canonical root set**; they are not
   re-solved.

**Claim (to be proven by tests, not assumed):** reachable states projected
onto `V` equal the slice's reachable states.

- *Full → slice.* An irrelevant action never writes `V`, so in projection it
  is a stutter. A relevant action's guard, effects and checks read only `V`,
  so it is enabled and does the same thing in the slice. Invariants outside
  the slice prune only full-model states, so the full projection is a subset
  of the slice.
- *Slice → full.* Replay the slice trace in the full model with irrelevant
  variables frozen at their root values. No irrelevant action fires; the
  root satisfies every invariant (otherwise it is reported as illegal anyway);
  invariants on frozen variables keep their truth value; mixed invariants are
  in the slice by rule 3.

Consequences, per verdict:

- `AlwaysHolds`, invariants, `Reachable`, `Unreachable`: exact; witnesses
  and counterexamples are valid full-model traces (only relevant actions
  appear).
- `NoDeadEnd` (recoverability, not deadlock): exact by the same replay
  argument.
- `DeadActions`: one slice per action, seeded with that action's reads.
- **Transition defects** (Field range, undeclared lifecycle edge, evaluation
  errors) of action `a` depend only on `a`'s cone, so the union of per-action
  slices finds exactly the defects that a whole-spec exploration finds.
- **Excluded actions** (event-payload guards) taint only the slices that
  contain them. Today any excluded action makes every invariant
  `INCONCLUSIVE`, so this is a precision gain.
- **Budget:** each slice has its own `max_states`. `INCONCLUSIVE` stays
  per-slice; it never turns into `PASS`.

**Gate (fail-closed):** a conformance test that, for every example and every
property where the unsliced exploration completes, requires the sliced
verdict, witness validity and finding set to equal the unsliced ones. It also
needs planted-defect probes: an invariant on a variable reached only through
a relevant action's *effect right-hand side*, through a *terminal lock*, or
through a *mixed invariant*. Each must still surface as `FAIL`
(review-gated-workflow lesson: the probes must show that a defect surfaces,
not only that two paths agree).

**Known limit:** a cross-cutting property, such as a sum over all accounts or
an invariant reading a hub field written by many actions, gets a large cone,
and the explosion returns. The broker benchmark is meant to measure how often
that happens in a realistic model.

## 6. Benchmark model: a generic retail broker

### 6.1 Why this domain

A retail FX/CFD broker is a large business system made of many **mostly
independent lifecycles** (client verification, trading accounts, payments,
partner status) coupled by a few hub facts (verification level, region,
equity). That is exactly the issue-#3 shape. The rules are common industry
practice, published widely by brokers and regulators, so the model can live
in the repository without private data.

**Neutrality rule:** the model is a composite of common practice and does not
describe, cite or name any particular provider. Every concrete number in it
is an illustrative assumption, chosen to keep domains small.

### 6.2 Domain rules (composite)

| Subsystem | Rules |
|---|---|
| Client profile & KYC | confirm contacts → personal details → economic profile → proof of identity → proof of address → verified; temporary document rejection; **final rejection after N failed attempts** (recoverable only via support); deposit limit rises in tiers with each completed step; some regions block deposits or trading until fully verified |
| Security | a client-wide confirmation method (email, SMS, authenticator); confirmation is required for withdrawals, partner changes, password and security changes |
| Trading accounts | account classes `CENT` / `STANDARD` / `PROFESSIONAL`; real or demo, **no demo for the cent class**; class is immutable after creation; per-client caps; archived after inactivity or manually; an archived account cannot trade or move money until restored; a disabled account needs reactivation through support |
| Leverage & risk | maximum leverage capped by equity bucket; an **uncapped tier** requires equity below a threshold **and** a minimum trading history; high-margin periods temporarily lower the cap; margin-call and stop-out thresholds per account class; stop out closes the least profitable orders first |
| Negative balance | the balance is reset to zero only by a protection operation after a full stop out that left it negative |
| Payments | no third-party payments; withdrawal currency = deposit currency; **withdrawal ≤ free margin**; **a submitted withdrawal cannot be cancelled**; available methods depend on region and verification |
| Swap-free | a client-wide status, on by default, revocable based on trading behaviour |
| Partners | tiered introducing-broker levels with an increasing commission share; automatic downgrade; restriction states *link blocked* / *on hold* / *blocked* with a capability matrix (client attribution, qualification, reward payments, withdrawal of accrued funds); *blocked* is irreversible; rebates to referred clients, optionally with manual approval |
| Client lifecycle | termination is permanent; the login email cannot be reused |
| Copy trading (optional) | performance fee charged only above the previous loss (high-water mark), settled per billing period |

### 6.3 Modelling assumptions

Each assumption is named in the spec and its README.

- A1. Money is abstracted to small bounded integers or tiers. Equity is a
  four-value bucket, and deposit limits are the tiers `LOW`/`HIGHER`/`NONE`.
- A2. Orders are a bounded `Scope` (2–3 slots) with lifecycle
  `open → closed | stopped_out`. Price is a nondeterministic `market_moves`
  action that changes an account's margin-level bucket.
- A3. Region is a fixed initial parameter (`Initial(vary=[Client.region])`)
  with three values: standard, deposits-blocked-until-verified,
  trading-blocked-until-verified.
- A4. Withdrawal lifecycle: `requested → processing → paid | rejected`, with
  no cancel transition; `rejected` returns the funds.
- A5. Inactivity archiving is an environment action guarded by "no open
  orders".
- A6. Partner level changes are environment actions guarded by abstract
  `meets_requirements` flags; volume and active-client numbers are not
  modelled.
- A7. N (failed document attempts before final rejection) is small in the
  model, e.g. 3.

### 6.4 Properties (the benchmark's queries)

A deliberate mix of local and cross-cutting properties, so the benchmark can
measure cone sizes:

| Id | Property | Expected cone |
|---|---|---|
| P1 | deposits never exceed the current verification tier's limit | KYC + payments |
| P2 | a withdrawal never exceeds free margin | one account |
| P3 | an archived or disabled account never trades or moves money | one account |
| P4 | uncapped leverage ⇒ equity below threshold ∧ trading-history eligibility | account + client history |
| P5 | a negative-balance reset happens only after a full stop out with balance < 0 | one account + orders |
| P6 | a blocked partner never gains attribution or rewards; accrued withdrawals stay possible | partner |
| P7 | a final KYC rejection is recoverable only through support (`NoDeadEnd` to `verified`) | KYC |
| P8 | a partner change or withdrawal always needs a security confirmation | security + partner/payment |
| P9 | a terminated client is frozen and its email is never reusable | client (cross-cutting via email) |
| P10 | reachable: a fully verified client on a professional account with uncapped leverage during a high-margin period | many subsystems |
| P11 | `DeadActions` over the whole model | per action |
| P12 | a cent-class demo account is unreachable | account creation |

### 6.5 Increments (a change series, measured per step)

M1 client profile + KYC + security → M2 trading accounts, archive/restore →
M3 deposits and withdrawals → M4 leverage, margin call, stop out, negative
balance → M5 partners → M6 multiplicity (2 accounts, 2 orders, 2 payment
methods, `Scope`) → M7 (optional) copy trading. Target at M5/M6: ≥ 8 entity
types, ≥ 7 lifecycles, 60–100 expanded actions, so it matches or exceeds the
private spec in issue #3.

## 7. Bake-off protocol (analint vs Quint)

For every increment, the same abstraction is written in both languages.
Recorded per tool:

- authoring: lines, number of concepts, time to the first green check;
- per property: verdict, states (analint, TLC distinct), wall time, peak
  memory, completeness (exhaustive, bounded depth k, or inductive proof);
- diagnostics: counterexample readability for a planted defect per
  increment;
- agent loop: whether an agent can orient (`show`/`affects`) and test a
  hypothesis (`--what-if`) without reading the whole source.

Quint runs: `quint verify --backend tlc` (exhaustive), Apalache
`--max-steps 10/20` (bounded), Apalache `--inductive-invariant` where a
strengthening is easy, and `quint run` (simulation) as the smoke test.
Cross-validation as in OAuth (research/24): the analint full-graph state count
must equal TLC's distinct-state count for the same bounds. A mismatch is a
modelling or semantics bug in one of them and blocks the comparison.

Following research/32, the result is an internal decision record, not a
public speed leaderboard.

## 8. Roadmap

Each phase is review-gated. The characterization snapshot must stay
unchanged unless a phase says otherwise.

**A. Engine hygiene (R1 + R3), small.** Share the canonical exploration
between invariants and default-source queries; lazy rejection messages;
precomputed per-action guard refs; trace only on defects; `deque`;
`changed_fields` only for artifact builds. Split `invariants_unchecked` into
`inconclusive` and `not_checked` (this is a JSON schema change, so bump the
check schema per research/30). Add a per-check `elapsed_ms`, states and
completeness, plus `analint check --max-states N`. Add an
`independent_lifecycles(k)` scaling family *with* per-component invariants
and a cross-component query (`workflow_product` has no properties).
*Exit:* the issue reproducer at K=7 runs ≥ 3× faster with identical
verdicts; snapshot unchanged.

**B1. Broker model M1–M3 in analint** (independent of A; can start in
parallel). It is written against the explicit composition root of
research/35, with one `Contract` per process, so that work lands first.
Assumption list, README, `expectations.toml` entry.
*Exit:* P1–P3, P7, P8, P11, P12 have verdicts or honest `INCONCLUSIVE`, with
measured times recorded here.

**C. Cone-of-influence slicing (R2).** Implement §5 behind the default
`check` path. JSON reports each slice (included entities, actions and
variables) and its completeness. `analint check --no-slice` keeps the
monolithic path for differential testing. *Exit:* the conformance test and
planted-defect probes from §5 pass; the K=7 reproducer is all `PASS` (exact)
in < 1 s; issue #3 gets a reply that the private spec can be rechecked.

**B2. Broker model M4–M6 in analint**, measured with and without slicing.
Record the cone size of each property. This is the evidence for whether
cross-cutting properties are common.

**D. Quint port of M1–M6** + the §7 protocol, run against each increment as
it lands. State-count cross-validation is mandatory.

**E. Decision synthesis (new research note).** Inputs: tables from B2 and D.
Possible outcomes:

1. analint alone is enough (slices are small and the rest is fast enough);
2. analint plus an **R4 compact state store** for the large cones;
3. analint as the authoring/agent frontend plus a **Quint/TLA+ export
   backend (R6)** for large cones or inductive proofs. This would reopen the
   research/25 deferral with an explicit consumer (the private spec from issue #3);
4. R5 partial-order reduction, if the large cones are dominated by
   interleavings rather than by distinct states.

**Deferred until E decides:** R4, R5, R6 and any native/Rust work
(research/17 §3 conditions still apply).

## 9. Should the private spec switch to Quint now?

Not yet, and not blindly:

- For the issue's shape, Quint+TLC is fast today only because brute force on
  the JVM still fits at K=7; one or two more lifecycles cost 8–64× more.
  Apalache's inductive mode scales, but it needs a hand-written inductive
  strengthening for each invariant. That is skilled work an analyst or agent
  will not do routinely.
- analint already gives that spec things Quint lacks: Python domain
  modelling, scenarios and flows, `show`/`affects`/`--what-if` for agents,
  simultaneous-effect semantics, and a three-valued verdict. Phases A and C
  are expected to make that spec's local properties exact and fast.
- If a deadline comes first: keep the analint spec as the source of
  truth, and hand-port only the 1–2 cross-cutting properties that stay
  `INCONCLUSIVE` to Quint (TLC). Phase D shows how expensive that port is;
  that cost is itself an input for the R6 decision.

## 10. Open questions for review

1. ~~Repository naming~~ — resolved: `examples/broker/`, neutral, per the
   §6.1 neutrality rule.
2. Include the optional copy-trading subsystem (M7)? It is a good
   high-water-mark fee model, but not core to the benchmark.
3. Should slicing be the default for `check` immediately, or opt-in for one
   release? Recommendation: default, with `--no-slice` and the conformance
   gate.

## Appendix A — Quint reproducer (K=7)

```quint
module repro {
  type S = A | B | C | D | E
  pure val K = 7
  pure val IDS = 0.to(K - 1)
  var st: int -> S
  var flag: int -> bool

  action init = all { st' = IDS.mapBy(_ => A), flag' = IDS.mapBy(_ => false) }

  pure def can(s: S, d: S, f: bool): bool = match s {
    | A => d == B or d == E
    | B => (d == C and f) or d == A or d == E
    | C => d == D or d == B
    | D => d == A or d == E
    | E => false
  }

  action move(i: int, d: S): bool = all {
    can(st.get(i), d, flag.get(i)), st' = st.set(i, d), flag' = flag,
  }
  action setFlag(i: int): bool = all {
    st.get(i) == B, flag' = flag.set(i, true), st' = st,
  }
  action step = nondet i = IDS.oneOf()
    any {
      nondet d = Set(A, B, C, D, E).oneOf() move(i, d),
      setFlag(i),
      all { st' = st, flag' = flag },  // stutter: terminal states are not deadlocks
    }

  val typeOK = st.in(setOfMaps(IDS, Set(A, B, C, D, E)))
    and flag.in(setOfMaps(IDS, Set(true, false)))
  val indInv = typeOK and inv
  val inv = IDS.forall(i => st.get(i) == C implies flag.get(i))
}
```

```bash
quint verify --backend tlc --invariant inv repro.qnt                  # exhaustive, 2,097,152 states
quint verify --invariant inv --max-steps 10 repro.qnt                 # Apalache, bounded
quint verify --invariant inv --inductive-invariant indInv repro.qnt   # Apalache, all depths
```
