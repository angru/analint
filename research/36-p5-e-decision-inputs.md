# 36 — P5 E: decision inputs from the broker benchmark

**Date:** 2026-10-10
**Status:** decision proposed (§4, 2026-10-11), awaiting review and the
acceptance run on the private spec; §1–§3 collect the measurements
**Inputs:** research/34 §8 (A, B1, B2, C, D), research/35

## 1. Question

ROADMAP P5 E chooses between: analint alone; analint plus a compact state
store (R4); analint plus a Quint/TLA+ export backend (R6); partial-order
reduction (R5). This note lists what the broker benchmark has measured so far
and what each option would still need to show.

## 2. Measurements

All on one laptop (macOS arm64, 8 cores, 16 GiB; CPython 3.14.5; Quint 0.32.0,
TLC via OpenJDK 17). Timings taken under equal load in interleaved A/B runs;
absolute numbers are informational.

### 2.1 Where analint's memory goes (M4 whole model)

| | before | after compact keys |
|---|---|---|
| traced bytes per explored state (20k) | 7,460 | 1,704 |
| RSS at 50k states | 559 MiB | 151 MiB |
| RSS at 1M states (capped) | — | 2.6 GiB |

The old key stored a `(label, field, value)` triple per field (~90 fields).
What remains per state: the value tuple (~770 B), the copy-on-write context
(~350 B), parent/order/edge bookkeeping (edges ~7–8 per state).

### 2.2 Where analint's time goes

Exploration was dominated by interpreted guard evaluation: ~40 candidate
actions per state, most rejected by their first guard. Compiling predicates to
closures (mirroring the interpreter, differential-tested), scanning only
changed entities for lifecycle checks and trimming per-transition overhead:

| run | start of night | now |
|---|---|---|
| M4 risk increment, 30k states, explore (equal load) | 18.3 s | 10.0 s |
| M4 risk increment, full explore, 54,084 states (idle) | 19.4 s | 10.2 s |
| `check benchmarks/broker/m4_risk.py` (idle) | 7.1 s | 3.9 s |
| `check examples/broker` (idle; research/34 D) | 2.7 s | 1.7 s |
| `check benchmarks/broker/m4.py --max-states 10000`, sliced + whole (equal load) | 19.7 s | 11.2 s |
| B2 harness at 10k, M4–M6 sliced / whole (idle, `results-10000.json`) | 6.1–6.5 / 2.0–2.4 s | 2.9–3.2 / 1.2–1.5 s |

Incremental successor generation (2026-10-12) skips work the parent state
already decided. A rejected action whose guard reads were not written by the
transition stays rejected (806k → 382k kernel calls for 20k M4-risk states),
and only invariants reading a written variable are re-checked. Graphs are
byte-identical. Interleaved A/B `check`: m4_risk 5.7 → 4.7 s, M4 at 10k
7.1 → 5.5 s, `examples/broker` 3.5 → 2.7 s, m6_profile_methods 8.4 → 5.4 s.
What remains is spread across accepted transitions (effects, field and
lifecycle checks, keys) and the remaining guard evaluations; no single
hot spot is left.

### 2.3 analint vs TLC on the same transition system

| model | distinct states | analint | TLC (8 workers) |
|---|---|---|---|
| broker M1–M3 (research/34 D) | 15,912 | full check 1.7 s (2.7 s before) | 1.2 s core, ~6 s wall |
| M4 risk increment, capacity 1 | 54,084 (both) | explore 10.2 s; `check` 3.9 s (invariants on an 18,028-state slice) | 2.2 s core, ~7 s wall |
| M6 risk increment, capacity 2 | 4,440,789 (both) | keys-only count 38 min, 1.7 GiB (under load); `explore()` would need ~11 GiB | 307 s (with M4 TLC running alongside) |
| full M4 (M3 × risk) | 286,428,912 (TLC) | > 1,000,000 (capped; 258 s, 2.6 GiB) | 2 h 16 min, all 13 invariants hold |

TLC finds distinct states roughly 5–10× faster than analint here (risk
increment: ~25k/s vs ~5k/s; M4 product: ~38k/s vs ~4k/s), and its fingerprint
set and queue spill to disk. State count, more than speed, separates the
tools: analint holds every state's context in memory.

### 2.5 R4 compact state store (implemented 2026-10-10)

A state is now its key: the layout id plus one 16-bit code per entity slot.
The code names a value tuple interned per layout slot (an escape covers codes
past 16 bits). Contexts are not kept: the BFS frontier carries its contexts,
and later scans rebuild them from keys with shared, read-only instances.
Parents and edges are integer arrays.

| | before | R4 |
|---|---|---|
| M4 risk increment, 54,084 states (tracemalloc, retained) | 3,784 B/state | 255 B/state |
| broker M3, 15,912 states | 1,624 B/state | 204 B/state |
| full M4, 300k states (max RSS, same run) | 809 MiB, 8.4k states/s | 263 MiB, 8.3k states/s |
| full M4, 2M states / 11.5M edges | (1M: 2.6 GiB) | 1.13 GiB, 316 s |
| `check` examples/broker, m4_risk (interleaved A/B) | 1.36 s, 3.52 s | 1.46 s, 3.66 s |

On the synthetic many-slot families (`scripts/bench_scaling.py`) memory per
state is 7.6–10× lower (conserved_transfer 4,232 → 412 B, workflow_product(7)
1,924 → 253 B), but exploration is 11–14% slower: encoding interns one value
tuple per entity slot. Edges (12 B each, ~6–8 per state) are now the largest
item. The 4–7% `check`
cost comes from rebuilding contexts for scans (invariants sharing an
exploration are verified in one pass). This moves the ceiling ~4–5× on a
laptop; it does not reach the full M4 product (286M states would still need
~150 GiB).

### 2.4 Slicing

Slicing keeps exact local proofs where cones are small (four KYC invariants
on 22-state slices at every increment; the four risk invariants on an
18,028-state slice of the risk increment). For genuinely coupled cones (money
conservation over M3 × risk) it does not help; the cone is the product.

### 2.6 R6 export to TLC (implemented 2026-10-11)

`check --tlc` hands every check the budget left INCONCLUSIVE to TLC
(`backends/tla.py` generates the module, `backends/tlc.py` runs it,
`validator/tlc_fallback.py` maps the answer back). The export is generated
from the same model analint explores, on the check's slice:

- one record variable per state slot (`present__` plus its fields; an absent
  slot is one canonical record), the projected roots as `Init`;
- each expanded action as `enabled /\ ok /\ next-state`: `pre` in order,
  presence guards for touched/created/deleted slots, the terminal lock; effects
  computed from the pre-state (simultaneous), saturation clamps;
- what the kernel treats as a defect — a hard Field bound, an undeclared
  lifecycle edge, a false `post` — disables the transition and is checked as
  its own TLC invariant `NoDefect_<action>`. A hit is reported as an error; the
  check stays undecided;
- invariants and inert roots (illegal outside the slice) as `CONSTRAINT`:
  TLC checks these states but does not expand them, which is analint's
  pruning;
- the target as a TLC invariant: an invariant as `applicable => holds`
  (and, when it reads Scope slots, a second run asks whether it is ever
  applicable — NOT_CHECKED otherwise). Unreachable/AlwaysHolds use the
  predicate; Reachable uses its negation, so a counterexample is the witness.

The export refuses, and the check stays INCONCLUSIVE, where TLA+ would not
follow analint: floats, `Min`/`Max` (an error on an empty scope), a read of a
slot that may be absent without a preceding `Present` guard (analint raises
an evaluation error there), event-payload guards. NoDeadEnd and DeadActions
have no TLC invariant form and are not exported.

Conformance (`tests/test_tlc_backend.py`, skipped without Java/jar):

- distinct-state counts equal analint's on every exportable example (whole
  model) and on every invariant slice of the examples and of the broker
  M5/M6 increments;
- `check --tlc` at a 5-state budget gives the same statuses and traces as
  analint at full budget;
- probes: terminal lock, presence guards on Create and on modification, inert
  roots, hard bounds, the NOT_CHECKED witness. Removing any of these from the
  generator fails a test.

| run | analint alone | with `--tlc` |
|---|---|---|
| `check benchmarks/broker/m4_risk.py` (default budgets) | 2 queries INCONCLUSIVE | both decided (one PASS on 1,945 states; one FAIL, same as analint at full budget — the increment never verifies the client); ~3 s extra |
| `check benchmarks/broker/m6_profile_methods.py` | 1 query INCONCLUSIVE | decided (PASS, 10,164 states, 1.2 s TLC) |
| `check benchmarks/broker/m4.py --max-states 10000` | risk invariants INCONCLUSIVE | the risk invariant's slice (risk × KYC × orders) did not finish within the 30-minute per-check timeout |

The last row is the limit: TLC moves the ceiling by roughly two orders of
magnitude (the full M4 product took 2 h 16 min by hand), not past it.

Found on the way: a capped exploration in which an invariant was never
applicable reported NOT_CHECKED ("never evaluable") instead of INCONCLUSIVE.
Fixed.

## 3. Reading of the options (proposal)

1. **analint alone** is adequate while each property's cone stays below
   roughly 10^5–10^6 states on a laptop. The M4 risk increment is inside; the
   full M4 product and the M6 risk increment (4.4M) are not.
2. **R4 compact store.** The next step is to stop storing contexts (rebuild
   from the key on demand) and to store edges as integer triples. Expected
   ~2–3× less memory: it moves the ceiling, it does not remove it; the M4
   product (286M states) would still need hundreds of GiB.
3. **R6 export to TLC** is the only option measured to finish the full M4
   product on this machine. The hand ports show the cost: every implicit
   kernel rule (presence, present-only quantifiers, terminal lock, `where=`
   pairings) must be generated exactly, and nondet parameters must be scoped
   per action (a shared choice made TLC enumerate ~900 successors per distinct
   state). State-count equality on the risk increments is the conformance
   gate such a generator would need. Implemented as `check --tlc` (§2.6),
   with that gate.
4. **R5 partial-order reduction**: the M4 product is largely interleavings of
   independent processes (M3 cash steps vs risk steps), so POR could cut it
   substantially for properties local to one process — but slicing already
   handles those; POR matters for coupled properties, whose coupled steps POR
   cannot reorder. Not measured.

Open: whether the private spec's coupled cones look like M4's money cone
(product-sized) or like the KYC/risk cones (small). That decides between
"analint + R4" and "analint + R6".

## 4. Proposed decision (2026-10-11)

**Layered, not either/or.** R4 and R6 are both implemented, and they cover
different ranges:

1. **Default: analint with slicing and the R4 store.** Every property kind
   (including NoDeadEnd and DeadActions), scenarios, flows and traces are
   decided in process, exactly. The practical ceiling is ~10^6 states per
   cone on a laptop (R4: 2M states in 1.13 GiB at ~8k states/s). Slicing keeps
   independent processes out of each other's cones, so for most properties
   the cone, not the whole spec, sets the cost.
2. **Opt-in second stage: `check --tlc` (R6).** For invariants and
   Reachable/Unreachable/AlwaysHolds queries whose cone exceeds the budget, on
   the same slice. The result is exact, or the export refuses. It is 5–10×
   faster and disk-backed: ~10^8 states in hours (full M4: 2 h 16 min). It is
   not the default because it needs Java and a TLC jar, costs a JVM start
   per check, and has no form for NoDeadEnd/DeadActions.
3. **R5 partial-order reduction: deferred.** Slicing already removes the
   independent processes that POR would collapse for local properties. What
   remains inside a coupled cone (e.g. two accounts' independent risk steps)
   could still be reduced, but no measured property needs it yet. Trigger:
   a real-spec cone beyond what `--tlc` finishes, or a NoDeadEnd/DeadActions
   cone beyond the in-memory ceiling.
4. **Model before engine.** The full M4 money cone is a product of separate
   settlement abstractions (M3 cash, risk equity, method settlement).
   Consolidating them would shrink it more than any reduction (research/34 §8
   B2). A product-sized cone is first a question about the model.

**Acceptance on the private spec** (the issue #3 trigger), run where the spec
lives; nothing leaves the machine:

```
analint check <spec> -f json > plain.json
analint check <spec> --tlc --tlc-timeout 1800 -f json > tlc.json
```

For each check, record `slice` (variables/actions), `states_explored`,
`status`, `backend` and `elapsed_ms`. Decision rule:

- everything PASS/FAIL without `--tlc` → nothing further; close P5;
- INCONCLUSIVE decided by `--tlc` → done; document `--tlc` for that spec, and
  consider per-check budgets;
- TLC timeouts → look at which processes the cone couples. If they are
  separate abstractions of one thing, change the model (4); otherwise
  R5 is triggered.
