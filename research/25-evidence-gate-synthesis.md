# Evidence-gate synthesis: how to continue the self-contained engine

**Date:** 2026-06-15

The evidence gate (research/20) existed to answer one question before any further
language growth: with two real, externally documented systems modelled and one of
them ported to a mature verifier, **does the evidence justify extending analint's
verification semantics with new primitives?** The gate is now passed; this is the
verdict it was built to inform. The comparison does not require analint to become
a front end for the other verifier.

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

**Neither of the two models demanded a new verification primitive within its
chosen abstraction.** Across nine measured requirement changes, the checked
properties were safety or reachability claims the current engine already
expresses. The event-pool/operational-`on` primitive deferred in research/22 was
never pulled in by either case. This is useful evidence, not a universal result
over all domains.

The boundaries and costs that *were* observed are different kinds of evidence:

1. **Reachability does not directly express temporal/liveness properties.**
   branch_protection change 1
   (dismiss-stale off) changed behaviour while every reachability query stayed
   green — only scenarios/flows caught it. History can be reified as explicit
   state, so this is not an absolute inability to model history; the principled
   boundary is first-class path/temporal semantics and fairness.
2. **"Who"-rules force identity and multiply state.** branch_protection change 3
   (approval by a non-pusher) needed reviewer identity and ×3.6'd the state space;
   OAuth's multiplicity is tractable but only with explicit `CodeId` plumbing.
   This is a modeling and scaling cost, not a fundamental verification boundary.
3. **`Contract` composes whole fragments, not refinements.** PKCE could not be a
   separate additive contract (it refines an existing entity and action), so it
   was integrated; a clean protocol/assurance split *is* possible and is
   no-semantic-change. Adding refinement/overlay semantics would need conflict
   rules, versioning and schema composition. This is a current authoring/API
   limitation, not a theorem about model checking.

Minor authoring friction was recorded (scope refs can't be field values;
contract-exported parameterized actions need explicit `id=`; relational queries
must constrain to non-default states). These are ergonomics items, not missing
verification power.

## analint vs Quint, honestly

| | analint | Quint / Apalache |
|---|---|---|
| Verification reach | exhaustive bounded reachability (safety, reachability classes) | + temporal/fairness vocabulary and symbolic backends |
| Conciseness for maps/relational joins | more plumbing | more concise |
| Authoring medium | domain-readable Python, no separate language | a dedicated spec language |
| Agent surface | `show` / `affects` / `--what-if`, rich scenario/flow diagnostics | not the focus |
| Auto-invariants from a canonical model | yes | manual |
| Spec-as-checkable-documentation | yes | spec, not doc |

Quint has a broader formal vocabulary and mature symbolic backends. The single
1169-state comparison does not establish a general scaling ranking. analint's
bounded checker is self-contained, exhaustive within its finite universe, and
well suited to the agent edit→check loop (research/08), which is the project's
primary scenario.

## Verdict

1. **Freeze semantic expansion, not engine development.** Keep bounded
   reachability as the current semantic scope and re-open new primitives only on
   repeated evidence pain from real models. Correctness, diagnostics,
   observability, reductions and performance of the existing engine remain active
   core work.
2. **Make exploration a first-class result.** Promote the internal BFS data into
   a stable run artifact with roots, rendered nodes, bound-action edges, state
   diffs, findings, shortest traces, fired/excluded actions, summary statistics
   and explicit completeness. This is the substrate for CLI, MCP and later
   visualization; it is not a public model IR.
3. **Measure before optimizing.** Add generated state-space families in the
   10²–10⁵ range, profile the reference explorer, then apply algorithmic
   improvements and reductions where measurements justify them.
4. **Continue dogfooding on larger real models.** New projects are acceptance
   tests for authoring friction, diagnostics and scaling. They may reopen
   semantics only when the same limitation recurs.

In one line: **analint's value is not "a better model checker" — it is a
domain-readable, agent-first specification with its own honest, exhaustive
bounded-reachability engine.**

### Why a Quint exporter is not the next step

The OAuth port was useful as an independent semantic comparison, but it does not
show that a production exporter is mechanical:

- analint has no temporal/fairness property to export, so an exporter cannot
  supply "beyond reachability" questions that the source model cannot express;
- arbitrary Python values and extension points do not automatically lower to
  Quint;
- diagnostics require stable source, action-binding and trace mapping;
- the verified Quint model added stuttering, so even this port is
  safety-equivalent rather than graph-identical.

A verifier bridge would introduce a second semantic implementation and an
external runtime without advancing the stated goal of a self-contained
framework. It is deferred until there is an explicit external-verifier use case.

## What this unblocks

- **DSL/type and example-intent audit**: the prerequisite before stabilizing a
  public result artifact.
- **Exploration artifact and diagnostics**: the first implementation milestone
  after those contracts are explicit.
- **Scaling characterization**: generated model families and measured
  algorithmic work.
- **Larger project models**: continued validation that the framework remains
  expressive and usable outside small examples.

Publication work (license, PyPI, docs site) is deliberately deferred until the
core workbench is useful enough to describe and debug further projects end to
end. A Quint exporter is also deferred and is not part of the active roadmap.

New verification primitives — event pool, time/concurrency, `Computed`, refinement
— remain gated on repeated, real evidence pain, which this exercise did not produce.
