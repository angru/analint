# 36 — P5 E: decision inputs from the broker benchmark

**Date:** 2026-10-10
**Status:** draft for review — collects measurements for ROADMAP P5 E; it does
not make the decision
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

| run (equal load) | start of night | now |
|---|---|---|
| M4 risk increment, 30k states, explore | 18.3 s | 10.0 s |
| `check examples/broker` (sliced) | 6.4–8.3 s | 3.6 s |
| `check benchmarks/broker/m4.py --max-states 10000`, sliced + whole | 19.7 s | 11.2 s |

### 2.3 analint vs TLC on the same transition system

| model | distinct states | analint | TLC (8 workers) |
|---|---|---|---|
| broker M1–M3 (research/34 D) | 15,912 | full check 2.7 s | 1.2 s core, ~6 s wall |
| M4 risk increment, capacity 1 | 54,084 (both) | explore ~10 s; sliced check of its 4 invariants 7 s (18,028-state slice) | 2.2 s core, ~7 s wall |
| M6 risk increment, capacity 2 | 4,440,789 (both) | keys-only count 38 min, 1.7 GiB (under load); `explore()` would need ~11 GiB | 307 s (with M4 TLC running alongside) |
| full M4 (M3 × risk) | > 196.7M (TLC, interim) | > 1,000,000 (capped; 258 s, 2.6 GiB) | ~2M distinct/min; > 90 min |

TLC finds distinct states roughly 5–10× faster than analint here (risk
increment: ~25k/s vs ~5k/s; M4 product: ~38k/s vs ~4k/s), and its fingerprint
set and queue spill to disk. State count, more than speed, separates the
tools: analint holds every state's context in memory.

### 2.4 Slicing

Slicing keeps exact local proofs where cones are small (four KYC invariants
on 22-state slices at every increment; the four risk invariants on an
18,028-state slice of the risk increment). For genuinely coupled cones (money
conservation over M3 × risk) it does not help; the cone is the product.

## 3. Reading of the options (proposal)

1. **analint alone** is adequate while each property's cone stays below
   roughly 10^5–10^6 states on a laptop. The M4 risk increment is inside; the
   full M4 product and the M6 risk increment (4.4M) are not.
2. **R4 compact store.** The next step is to stop storing contexts (rebuild
   from the key on demand) and to store edges as integer triples. Expected
   ~2–3× less memory: it moves the ceiling, it does not remove it; the M4
   product (> 196.7M states) would still need hundreds of GiB.
3. **R6 export to TLC** is the only option measured to finish the full M4
   product on this machine. The hand ports show the cost: every implicit
   kernel rule (presence, present-only quantifiers, terminal lock, `where=`
   pairings) must be generated exactly, and nondet parameters must be scoped
   per action (a shared choice made TLC enumerate ~900 successors per distinct
   state). State-count equality on the risk increments is the conformance
   gate such a generator would need.
4. **R5 partial-order reduction**: the M4 product is largely interleavings of
   independent processes (M3 cash steps vs risk steps), so POR could cut it
   substantially for properties local to one process — but slicing already
   handles those; POR matters for coupled properties, whose coupled steps POR
   cannot reorder. Not measured.

Open: whether the private spec's coupled cones look like M4's money cone
(product-sized) or like the KYC/risk cones (small). That decides between
"analint + R4" and "analint + R6".
