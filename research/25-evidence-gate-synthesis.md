# Evidence-gate synthesis: extend the engine, or front-end an existing verifier?

**Date:** 2026-06-15

The evidence gate (research/20) existed to answer one question before any further
language growth: with two real, externally documented systems modelled and one of
them ported to a mature verifier, **does the evidence justify extending analint's
verification core with new primitives, or should analint be positioned as a
domain front end over an existing verifier?** The gate is now passed; this is the
verdict it was built to inform.

## What was collected

Two external models, each built as a measured change series, plus a Quint port.

- **`examples/branch_protection`** (research/23) — a single-entity GitHub
  protected-branch policy; a four-change requirement series.
- **`examples/oauth`** (research/24) — OAuth 2.0 authorization-code + PKCE; a
  five-change series reaching two clients, two code/token scopes, relational
  provenance and replay revocation (1169 states, 2256 edges).
- **`examples/oauth/oauth.qnt`** — the same bounded model in Quint 0.32.0:
  typecheck + tests + 10k-trace simulation + symbolic `quint verify` (Apalache,
  `allSafety`) all clean.

## What the evidence found

**No real model demanded a new verification primitive.** Across nine measured
requirement changes, every property that mattered was a safety or reachability
claim the current engine already expresses. The event-pool/operational-`on`
primitive deferred in research/22 was never pulled in by either case.

The boundaries that *were* hit are principled, not accidental gaps:

1. **Reachability cannot see history/liveness.** branch_protection change 1
   (dismiss-stale off) changed behaviour while every reachability query stayed
   green — only scenarios/flows caught it, because "stale" is a path property.
   This is the safety/liveness divide, fundamental to all verification, and it is
   exactly where Quint/TLA+ + Apalache are strictly stronger (temporal logic,
   fairness, symbolic proof).
2. **"Who"-rules force identity and multiply state.** branch_protection change 3
   (approval by a non-pusher) needed reviewer identity and ×3.6'd the state space;
   OAuth's multiplicity is tractable but only with explicit `CodeId` plumbing.
3. **`Contract` composes whole fragments, not refinements.** PKCE could not be a
   separate additive contract (it refines an existing entity and action), so it
   was integrated; a clean protocol/assurance split *is* possible and is
   no-semantic-change. Adding refinement/overlay semantics would need conflict
   rules, versioning and schema composition — far more than one case justifies.

Minor authoring friction was recorded (scope refs can't be field values;
contract-exported parameterized actions need explicit `id=`; relational queries
must constrain to non-default states). These are ergonomics items, not missing
verification power.

## analint vs Quint, honestly

| | analint | Quint / Apalache |
|---|---|---|
| Verification reach | bounded reachability (safety, reachability classes) | + temporal, fairness, symbolic proof, larger scale |
| Conciseness for maps/relational joins | more plumbing | more concise |
| Authoring medium | domain-readable Python, no separate language | a dedicated spec language |
| Agent surface | `show` / `affects` / `--what-if`, rich scenario/flow diagnostics | not the focus |
| Auto-invariants from a canonical model | yes | manual |
| Spec-as-checkable-documentation | yes | spec, not doc |

Quint is the stronger *verifier*. analint is the stronger *authoring + change-impact
+ agent* surface, and its bounded checker is fast and in-process — well suited to
the agent edit→check loop (research/08), which is the project's primary scenario.

## Verdict

1. **Do not expand the verification primitives.** Freeze the core at bounded
   reachability — its honest, decidable, useful scope. Re-open this only on
   *repeated* evidence pain from real models, not a single case (the standing rule
   from research/24's execution rule).
2. **Invest in the differentiated layer**, not in re-implementing a model checker:
   the agent/authoring surface (`affects`, `--what-if`, exploration artifacts),
   domain readability, scenario/flow diagnostics, and spec-as-living-documentation.
3. **Offer a Quint export bridge as the answer to "beyond reachability".** The
   oauth.qnt port shows the analint→Quint mapping is largely mechanical
   (entity+scope → maps over finite keys; actions → `any { ... }`; invariants →
   boolean predicates). Rather than grow temporal/symbolic machinery inside
   analint, let analint be the domain-readable, agent-friendly front end that can
   *hand off* to Quint/Apalache when a question exceeds reachability. This realises
   the roadmap's "domain frontend over an existing verifier" option as a **bridge**,
   while keeping analint's own fast bounded checker for the common case.

In one line: **analint's value is not "a better model checker" — it is a
domain-readable, agent-first specification and fast bounded-reachability linter,
with a path to export to a heavyweight verifier when the question demands it.**

## What this unblocks

- **Ecosystem / publication** (roadmap parallel track), now that names are stable
  and the engine scope is settled: license, packaging, CI, a docs site.
- **Agent-surface depth**: the exploration-result artifact (roots/nodes/edges/
  traces/completeness) already pending in the roadmap, feeding CLI/MCP/visualisation.
- **A Quint-export experiment** (optional, evidence-driven): a generator from an
  analint `Spec` to a `.qnt` module, validated by re-deriving oauth.qnt.

New verification primitives — event pool, time/concurrency, `Computed`, refinement
— remain gated on repeated, real evidence pain, which this exercise did not produce.
