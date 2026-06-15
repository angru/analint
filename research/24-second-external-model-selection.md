# Selecting the second external evidence model

**Date:** 2026-06-15

## Decision

Use **OAuth 2.0 Authorization Code Grant with PKCE** as the second external
evidence model.

The choice is not based on domain familiarity. It is based on the evidence gap
left by `examples/branch_protection`: analint now needs a real system with
multiple identities, cross-object bindings, an adversarial path, and a natural
extension that can be composed with a core model. OAuth plus PKCE provides all
four without making real time, fairness, or unbounded queues prerequisites.

The runner-up is a combined Kubernetes ReplicaSet and ResourceQuota model. It
is valuable, but its central promise is eventual reconciliation, which the
current reachability-only engine cannot verify honestly.

## Selection criteria

The second case should:

1. describe an externally documented system rather than a benchmark invented
   for analint;
2. require several bounded instances and explicit identity relationships;
3. exercise `Contract` composition rather than only file organization;
4. support meaningful safety and reachability properties with the current
   engine;
5. admit a sequence of realistic requirement changes with measurable blast
   radius;
6. be small enough to port to Quint or FizzBee without reducing either model
   to a toy;
7. expose a framework limit without requiring a new primitive before the
   experiment starts.

## Ranked shortlist

| Candidate | Composition and identity | Current-engine fit | Main evidence | Main risk | Verdict |
|---|---|---|---|---|---|
| OAuth Authorization Code + PKCE | High | High | Client/code/token binding, replay, RFC extension | Cryptography must be abstracted | **Selected** |
| Kubernetes ReplicaSet + ResourceQuota | High | Medium | Competing owners, capacity policy, controller actions | Important claim is liveness/fairness | Runner-up |
| ACME certificate issuance | High | Medium-high | Order/authorization/challenge hierarchy | Can collapse into another lifecycle model | Strong later case |
| SQS visibility timeout + dead-letter queue | High | Low | Multiple workers, retries, duplicate delivery | Time and delivery semantics dominate | Defer |
| Stripe PaymentIntent | Medium-low | High | Documented state transitions and failures | Repeats fulfillment and single-lifecycle strengths | Do not use second |

This ranking deliberately penalizes candidates whose most important behavior
cannot be stated by analint today. A model is not useful evidence if success
depends on silently weakening its real contract.

## Recommended bounded OAuth model

### External basis

- [RFC 6749 section 4.1](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.1)
  defines the Authorization Code Grant.
- [RFC 6749 section 4.1.3](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.1.3)
  binds token redemption to a valid code, client, and redirect URI.
- [RFC 6749 section 10.5](https://www.rfc-editor.org/rfc/rfc6749.html#section-10.5)
  requires short-lived, single-use authorization codes bound to the client and
  redirect URI.
- [RFC 7636 section 4.6](https://www.rfc-editor.org/rfc/rfc7636.html#section-4.6)
  adds verification of the `code_verifier` against the challenge attached to
  the authorization request.

The source matrix for the implementation must separate these requirements from
our bounded abstractions. In particular, the model must not claim to verify
HTTP, TLS, browser behavior, entropy, hashing, or expiration.

### Bounded state

Start with:

- two clients;
- two redirect URI values;
- two authorization-code slots;
- two access-token slots;
- a finite set of verifier/challenge values;
- code status: unused, redeemed, or invalidated;
- token status: absent, active, or revoked;
- explicit code-to-client, code-to-redirect, code-to-challenge, and
  token-to-client bindings.

Use slots and finite identity values rather than dynamic strings. This makes
the identity relationships visible to the explorer and keeps the state graph
measurable.

### Contract structure

The initial hypothesis was that client registration, the authorization-code
core, and PKCE might be separate contracts. The implementation rejected that
split rather than forcing it: contracts should follow real ownership boundaries,
and PKCE changes existing code state and redemption behavior.

**Finding (decided 2026-06-15): PKCE cannot be a separate additive contract.**
`Contract` (src/analint/models/contract.py) is a closed union of whole
behavioural fragments with identity deduplication. It offers no entity-schema
extension and no way to add a guard/effect to an existing action. PKCE *refines*
an existing entity (a `challenge` field on `AuthCode`) and an existing transition
(a verifier guard on `redeem_code`). A parallel PKCE redemption action would
leave the original `redeem_code` as a PKCE bypass; closing that bypass requires
modifying or excluding the core action, which is no longer additive composition.
Precise conclusion: *whole-fragment composition works; cross-cutting behavioural
refinement is unsupported*. PKCE is therefore integrated into the canonical model
(`examples/oauth/protocol.py`), and this failed expectation is kept as the evidence.
One case does not justify adding refinement semantics (`Action.refine()`,
overlays, replacement) — those need conflict rules, version semantics and
entity-schema composition.

**Positive composition result (completed after step 5):** the final example is a
three-file package:

- `protocol.py` exports `oauth-protocol`: entities, scopes, and actions;
- `assurance.py` exports `oauth-assurance`: scenarios, flows, and properties over
  the protocol's public objects;
- `spec.py` is the root and imports both contracts.

The split is genuinely no-semantic-change: the characterization snapshot,
1169-state count, state hash, edge hash, scenarios, flows, and verdicts are
unchanged. This proves explicit composition of whole behavioral fragments and a
separately owned assurance suite. It does **not** overturn the PKCE finding:
composition works at exported-object boundaries; behavioral refinement does not.

The split exposed one API-ordering friction. Parameterized actions are expanded
when `Spec` is constructed, before the loader can derive IDs from module variable
names. Contract-exported parameterized action families therefore need explicit
`id=` values. The existing composition fixture did not expose this because its
action is not parameterized. This is a real limitation of the current
"IDs are optional" promise, but not evidence for a new DSL primitive.

### Baseline actions

- issue a code after an approved authorization request;
- redeem a code with client and redirect identity;
- redeem a code with a verifier once PKCE is enabled;
- attempt redemption as another client;
- attempt redemption with another redirect URI;
- intercept and attempt to redeem another client's code;
- replay an already redeemed code;
- optionally revoke tokens derived from a detected replay.

Attacker attempts should be ordinary actions with explicit identities, not a
special security-testing API.

### Required properties

At minimum:

- a token is issued only to the client bound to the code;
- a token is issued only when the redirect URI matches the code binding;
- an authorization code cannot successfully issue tokens twice;
- with PKCE enabled, a wrong verifier cannot obtain a token;
- an intercepted code without the verifier cannot obtain a token;
- the honest authorization and redemption flow remains reachable;
- adding a second client does not weaken properties scoped to the first;
- if replay-triggered revocation is modeled, all affected tokens become
  unusable and unrelated tokens remain active.

These are safety and reachability claims. Do not describe them as complete
OAuth security.

### Change series

Save and measure these changes independently:

1. implement the RFC 6749 authorization-code core for one client;
2. enforce exact redirect URI binding;
3. add PKCE — planned as a separate contract, but it refines existing state and
   transitions, so it is integrated (see the Contract finding above);
4. add a second client and intercepted-code attacker actions;
5. add replay detection and the selected token-revocation policy.

For each change record:

- source requirement;
- spec diff size;
- affected actions, invariants, scenarios, and queries;
- explored state count and verdict;
- whether the change crossed a composition or identity boundary;
- behavior that Quint or FizzBee expresses more directly.

The third and fourth changes are the real gate. If adding PKCE or the second
client requires broad duplication, hidden singleton assumptions, or
unreadable identity plumbing, the framework has not passed the evidence test.

## Implementation results

The five changes were committed independently and measured against the
characterization snapshot:

| Step | Commit | Requirement change | Model diff | Reachable states |
|---|---|---|---:|---:|
| 1 | `d5fdb95` | authorization-code core | +151 | 3 |
| 2 | `202d9f8` | exact redirect binding | +54 / -12 | 5 |
| 3 | `376a8c5` | integrated PKCE | +94 / -42 | 9 |
| 4 | `b0ffc10` | two clients, two code slots, two token slots, interception | +267 / -91 | 497 |
| 5 | `9409a7d` | replay detection and derived-token revocation | +181 / -13 | 1169 |

All counts are complete bounded explorations, not sampled traces. The final
model has six scenarios, two executable flows, eight queries, 1169 states, and
2256 edges. No new framework primitive was added.

### What passed

- Multiplicity over two independent scopes remained tractable at this size.
- Client, redirect, verifier, and code-to-token provenance properties are
  expressed relationally with `ForAll`/`Exists`.
- The wrong-client test isolates client binding: removing only that guard makes
  both its scenario and `no_token_to_wrong_client` fail.
- The unrelated-token test isolates provenance: removing
  `token.source_code == code_id` makes revocation affect the wrong token.
- Replay is denied as a second redemption and moves the source code/token pair
  to `REPLAY_DETECTED`/`REVOKED`; no second token is created.
- The later multi-file `Contract` split preserved the exact graph.

### Modeling friction

1. A `Scope` reference cannot be stored as a field value. The model introduces
   `CodeId` and pins each slot to its value-level identity through static
   `where=` implications. Quint's map key is directly usable as provenance, so
   it needs no parallel ID field.
2. Relational negative properties initially matched untouched slots carrying
   default `code_id` values. Requiring the joined code to be `REDEEMED` or
   `REPLAY_DETECTED` removed the false positive. Defaults remain part of state
   even when a slot is semantically unused.
3. PKCE could not be an additive contract because it refines an existing entity
   and action.
4. Parameterized contract actions require explicit IDs because expansion occurs
   before loader-derived naming.

These are useful framework constraints, but none yet justifies a new primitive.

## Quint 0.32.0 comparison

The same bounded protocol and property set is ported in
`examples/oauth/oauth.qnt`. It uses two code-map keys, two token-map keys, the
same finite client/redirect/verifier domains, and the same issue, redeem, and
replay/revoke transitions.

Reproducible commands:

```bash
npx --yes @informalsystems/quint@0.32.0 typecheck examples/oauth/oauth.qnt
npx --yes @informalsystems/quint@0.32.0 test examples/oauth/oauth.qnt \
  --main=oauth --match='test.*' --verbosity=3
npx --yes @informalsystems/quint@0.32.0 run examples/oauth/oauth.qnt \
  --main=oauth --invariant=allSafety --max-samples=10000 \
  --max-steps=20 --seed=0x5eed
```

Observed on 2026-06-15:

- typecheck passed;
- five deterministic run tests passed;
- the seeded 10,000-trace simulation found no safety violation;
- `quint verify --invariant=allSafety --max-steps=7` could not start because
  Apalache requires a Java runtime and this machine has none.

The simulation result is **not** claimed as symbolic proof. analint exhaustively
enumerated 1169 distinct states in-process; Quint's comparable symbolic
verification remains an environment prerequisite, not a model failure.

### Comparative verdict

| Concern | analint | Quint |
|---|---|---|
| Bounded state representation | Domain-shaped `Entity` + `Scope` | Maps over finite key sets |
| Provenance identity | Extra `CodeId` plus slot-to-ID relation | Map key used directly |
| Safety syntax | `AlwaysHolds` / `Unreachable`, nested bounds | Boolean invariant over maps and sets |
| Positive/rejection examples | `Scenario` and executable `Flow` with detailed rule diagnostics | Concise `run` chains and `.fail()` |
| Exploration result here | Exhaustive: 1169 states, 2256 edges | 10,000 sampled traces; symbolic run blocked by missing Java |
| Source size | 551 lines for protocol + assurance, 26-line root | 285-line combined model and tests |
| Composition evidence | Explicit versioned contracts, but no dependency declaration or refinement | Native modules/imports; this port is one module |

Quint is notably more concise for finite maps, relational joins, and action
composition. analint's advantage in this case is not raw expressiveness: it is
the domain-shaped Python authoring surface, exact small-state exploration without
a JVM, and diagnostics organized around scenarios, flows, actions, and affected
fields. The OAuth case therefore supports the narrower project positioning; it
does not justify competing with Quint on temporal logic or general model
checking.

## Kubernetes runner-up

If the project intentionally wants an infrastructure-domain case instead, use
**ReplicaSet plus ResourceQuota**, not either feature alone.

- A [ReplicaSet](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/)
  creates or deletes Pods to move the selected population toward the desired
  replica count.
- A [ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
  can reject resource creation; Kubernetes explicitly notes that a higher-level
  workload may be accepted while later Pod creation fails because of quota.

A bounded model with two ReplicaSets sharing four or five Pod slots would test
ownership, filtered counts, competing controllers, and admission policy.
Useful properties include quota safety, ownership-safe deletion, reachable
under-replication under exhausted quota, and reachable convergence when
capacity exists.

However, "the ReplicaSet eventually converges" requires a scheduling/fairness
assumption. Current analint can show that a converged state is reachable and
that bad states are or are not reachable; it cannot prove eventual progress.
That makes this a strong future temporal-semantics case, but a weaker immediate
composition gate than OAuth.

## Other candidates

### ACME

[RFC 8555](https://www.rfc-editor.org/rfc/rfc8555.html) provides a real
order-to-authorizations-to-challenges hierarchy. It is a good later case for
hierarchical composition and multiple identifiers. Its baseline should omit
expiration and network validation, and it must avoid becoming only another
status lifecycle.

### SQS visibility and dead-letter queues

This would stress multiple messages, multiple consumers, retries, duplicate
delivery, and redrive policy. Those are useful demands, but time and
at-least-once delivery are central rather than optional. Choosing it now would
mostly demonstrate already-known missing semantics.

### Stripe PaymentIntent

This remains implementable with the current DSL, but it overlaps heavily with
the existing fulfillment saga and lifecycle examples. It would add fidelity
evidence without adequately testing composition or multiplicity, so the older
recommendation in research/20 is superseded.

## Execution rule

Implement the OAuth baseline without adding DSL primitives. Record friction as
evidence first. A new primitive is justified only if:

1. the requirement is explicit in RFC 6749 or RFC 7636;
2. the same problem survives a reasonable bounded encoding;
3. the issue is semantic rather than cosmetic;
4. Quint or FizzBee comparison shows that the missing concept materially
   improves the model.

The case is complete only after the same bounded protocol and property set is
ported to Quint or FizzBee. An analint-only model validates the example, not
the framework's positioning.
