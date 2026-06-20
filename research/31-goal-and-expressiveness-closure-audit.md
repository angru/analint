# Goal and expressiveness closure audit

**Date:** 2026-06-20

**Question:** can the current analint semantic model describe and verify the
systems the project intends to cover, or is another language/engine feature
required before the public contract is frozen?

This is stricter than the earlier evidence gate. The evidence gate asked whether
two external examples demanded a new primitive. This audit starts from the
project's product claims, constructs a capability model, maps it to executable
evidence, and then attacks it with requirements that should fail if the scope is
stated honestly.

`ROADMAP.md` remains the source of truth for status. This document defines the
semantic boundary that documentation and publication claims must respect.

---

## 1. Verdict

**The current semantic model is sufficient for the intended product scope. No
new verification primitive is required before documentation or the first public
release.**

That verdict is conditional on stating the scope precisely:

> analint describes and exhaustively checks small, finite abstractions of domain
> behaviour: state, guarded atomic transitions, invariants, concrete journeys,
> safety, reachability, recoverability, and dead actions.

It is not a language for:

- liveness or fairness proofs;
- unbounded object populations, queues, recursion, or arbitrary data;
- real-time deadlines and continuous time;
- probabilistic guarantees or quantitative simulation;
- instruction-level concurrency and weak-memory races;
- proving conformance of an implementation to the model;
- prose, UI, persistence, transport, or deployment topology unless those are
  deliberately abstracted into finite domain state.

Within the stated finite-state scope, the language is semantically adequate.
Most apparent missing features can be compiled into existing primitives:

- nondeterministic outcomes → multiple enabled actions or a finite outcome
  `Param`;
- conditional effects → guarded action variants;
- bounded dynamic objects → `Scope` + presence + `Create`/`Delete`;
- maps and relations → scoped entities whose fields hold finite identities;
- path/history-sensitive safety → explicit monitor/history state;
- derived values → named expressions and aggregates;
- hierarchy → multiple state fields or a flattened finite product;
- retries/timeouts → bounded counters and explicit actions, when the claim is
  about the chosen bound rather than real time or fairness.

Those encodings may be verbose. Verbosity and modularity are authoring problems,
not evidence that the transition model is incomplete. The cleanup in research/30
should proceed; semantic expansion should remain frozen.

One publication-blocking issue was found: some fulfillment text says
`NoDeadEnd` proves that the saga "always settles", "never wedges", or that
"every run must terminate". It proves the weaker and precise claim that a
settled state remains **reachable from every reachable state**. It does not prove
inevitable progress. The wording must be corrected before publication; the
engine does not need a liveness feature to preserve the intended bounded
reachability scope.

This is **semantic closure, not product validation**. The audit does not prove
that non-programmer analysts will author the Python DSL comfortably, that teams
will maintain a second model over years, or that an implementation conforms to
the model. Those require user evidence and integration/tooling, not another
state-transition primitive.

---

## 2. Product goals converted into testable obligations

The project currently serves three user groups and four model classes. Vague
goals such as "describe systems" are not testable, so they are reduced here to
explicit obligations.

### 2.1. Users

| User | Required outcome |
|---|---|
| Analyst/domain expert | Read named state, rules, transitions, examples, and counterexample traces without temporal-logic notation |
| Developer | Encode finite domain behaviour precisely; review changes; run checks in CI |
| Coding agent | Inspect the model, assess impact, test a hypothesis, and receive structured fail-closed results |

### 2.2. Intended model classes

| Model class | Required questions |
|---|---|
| Product/domain workflow | Which states are valid? Which transitions are allowed? Can every reachable situation still recover? |
| Policy/authorization abstraction | Can a forbidden decision occur? Is an allowed decision achievable? Which identity/resource relation matters? |
| Game/narrative mechanics | Are endings/content reachable? Can the player softlock? Are resources conserved? |
| Bounded protocol/controller abstraction | Can safety be violated under any action order? Can important states be reached from every bounded root? |

### 2.3. Required semantic capabilities

To answer those questions, the DSL needs:

1. typed finite state and finite identity;
2. one or many admissible initial states;
3. reusable state predicates and finite quantification;
4. atomic guarded transitions with simultaneous updates;
5. finite nondeterministic branching;
6. bounded creation/deletion;
7. concrete one-step and multi-step examples;
8. exhaustive bounded exploration;
9. safety, reachability, recoverability, and dead-action queries;
10. fail-closed handling of unsupported or incomplete exploration;
11. inspectable structure and deterministic machine results.

All eleven exist today. Sections 4 and 5 map them to executable evidence.

### 2.4. Product goals that are not expressiveness claims

| Goal | Current status | What would close it |
|---|---|---|
| Agents can orient, inspect impact, test hypotheses, and consume traces | implemented | continued dogfooding and stable JSON contracts |
| Analysts without a programming background can read the model | plausible, not independently validated | observed review/usability sessions |
| Analysts without Python can author the model | not established and not required for first release | user research; possibly generated/table views, not automatically a new DSL |
| The model stays synchronized with production code | not provided | MBT, trace replay, runtime conformance, or a lighter evidence-backed bridge |
| The verifier scales to arbitrary product size | false | abstraction, decomposition, reductions, larger measured models |
| The project has a unique market niche | still a positioning hypothesis | adoption and comparative user evidence |

The first-release semantic contract can be frozen while these remain open. They
must not be misreported as solved by language expressiveness.

---

## 3. Formal adequacy for the bounded scope

### 3.1. Constructive finite-state encoding

Consider any finite labelled transition system:

```text
M = (S, I, L, R)

S = finite states
I ⊆ S = admissible initial states
L = transition labels
R ⊆ S × L × S = transition relation
```

analint can encode it directly:

- represent each state in `S` as one enum value in one `Entity` field;
- represent `I` with defaults or `Initial(vary=..., where=...)`;
- for each edge `(s, label, t)`, declare an `Action` guarded by `state == s`
  and setting `state` to `t`;
- use multiple actions or finite parameter bindings for multiple outgoing
  edges;
- ask state properties with the existing query set.

This trivial construction proves a useful lower bound: **every finite transition
graph is representable**.

Real models do not use one giant enum because factored fields, scopes, and named
predicates are more readable and reduce duplicated declarations. But those are
factorizations of the same finite-state model, not a different semantic class.

### 3.2. Richer bounded encodings

The implemented advanced surface preserves the finite-state argument:

- finite scalar domains: bool, enums, bounded integers, `Field(values=...)`;
- bounded multiplicity: `Scope` creates a fixed finite universe;
- dynamic membership: presence is one more finite state component;
- relations: endpoint identities are finite scalar fields;
- quantifiers and aggregates: exhaustively evaluated over present scope slots;
- `Param`: finite Cartesian expansion into concrete actions;
- `Initial`: finite Cartesian expansion filtered by predicates;
- `Create`/`Delete`: presence transitions inside the fixed universe.

The state graph remains finite when every changing field and scope is finite.

### 3.3. Determinism is not a restriction on the transition relation

One concrete action binding has one simultaneous result. The model as a whole is
nondeterministic because every enabled action/binding is explored.

These are equivalent for bounded verification:

```text
one action with outcomes {success, failure}
```

and:

```text
success action with guard G
failure action with guard G
```

or a single parameterized family over a finite `outcome` domain. The latter two
may produce more explicit trace labels, which is usually beneficial for domain
review.

Therefore a first-class `Choice`/`outcomes` primitive is optional sugar, not a
semantic requirement.

### 3.4. Conditional effects are reducible

An action:

```text
if P then effect A else effect B
```

can be represented as two actions:

```text
pre ∧ P     → A
pre ∧ ¬P    → B
```

This preserves the reachable graph. It can increase declaration volume and
scenario rebinding, as the branch-protection requirement series demonstrated.
That is evidence for possible future sugar only if the pattern becomes frequent;
it is not a current expressiveness gap.

### 3.5. History can be reified, but liveness cannot be wished away

A path fact such as "an approval happened after the latest push" is not a
predicate of the current abstract state unless the model stores enough history:

```text
latest_push_revision
approval_revision
```

Adding those fields makes the property state-based and checkable. More generally,
a finite-state monitor can compile regular finite-trace safety properties into
ordinary model state.

This does **not** turn reachability into temporal logic. Claims such as:

```text
every request eventually receives a response under a fair scheduler
```

quantify over infinite executions and scheduling assumptions. They are outside
the current verifier even if a few history bits are added.

The distinction is:

- finite history needed to decide a safety state → encode as state;
- inevitable progress/fairness over executions → unsupported by design.

---

## 4. Capability-to-evidence matrix

The evidence is executable: example intent and graph characterization tests
currently pass (`26 passed, 1 skipped` for
`test_characterization.py` + `test_example_expectations.py` on 2026-06-20).

| Capability | Executable evidence | Result |
|---|---|---|
| Scalar typed state, domains and lifecycles | ecommerce, cloak, fulfillment; model tests | covered |
| Cross-entity predicates and invariants | fulfillment, branch protection | covered |
| Simultaneous multi-field updates | ecommerce, OAuth; transition conformance tests | covered |
| Arithmetic expressions and conservation properties | coin | covered; deliberately finds overflow |
| Multiple bounded instances | coin, OAuth, Kubernetes | covered |
| Finite quantifiers and aggregates | coin, OAuth, Kubernetes | covered |
| Parameterized action families | coin, mafia, OAuth, Kubernetes | covered |
| Multiple admissible initial states | mafia, Kubernetes | covered |
| Bounded creation/deletion and presence | Kubernetes; create/delete tests | covered |
| Positive and blocked one-step examples | every major example | covered |
| Executable multi-step journeys | branch protection, OAuth, Kubernetes, taskboard | covered |
| Reachability witnesses | cloak, mafia, OAuth, Kubernetes | covered |
| Safety counterexamples | coin, trollbridge | covered |
| Recoverability/softlock detection | cloak, fulfillment, Kubernetes, trollbridge | covered |
| Dead action detection | cloak, coin, fulfillment, Kubernetes, sunless crypt | covered |
| Composition with explicit exports | OAuth contracts | covered |
| Human/agent introspection | `show`, `affects`, exploration artifact, trace | covered |
| Honest incomplete result | unbounded/capped/excluded tests | covered |

### 4.1. Breadth of current executable models

The characterized examples include:

| Example | Main pressure | Reachable states / edges |
|---|---|---:|
| branch protection | policy and requirement changes | 121 / 383 |
| cloak | narrative reachability and softlock freedom | 27 / 45 |
| coin | multiplicity, parameters, sum invariant | 216 / 3,096 |
| fulfillment | saga branches and compensations | 34 / 46 |
| Kubernetes | two controllers, quota, presence, ownership | 1,792 / 13,008 |
| mafia | nondeterministic initial role assignments | 36 / 42 |
| OAuth | identity, provenance, replay revocation, composition | 1,169 / 2,256 |
| sunless crypt | playable finite game mechanics | 716 / 1,669 |
| troll bridge | intentionally found underflow and softlock | 9 / 9 |

This is not proof over every domain. It is enough to show that the semantic
features compose beyond isolated unit tests.

---

## 5. Goal coverage by model class

### 5.1. Product/domain workflows — sufficient

Current primitives cover:

- lifecycle states and allowed transitions;
- preconditions and postconditions;
- compensation branches;
- field and world invariants;
- bounded resources and identities;
- concrete examples and journeys;
- forbidden outcomes, achievable goals, and recoverability.

The fulfillment model demonstrates the intended abstraction: reservation,
payment, shipment, failures, and compensations as domain state. Queues, HTTP,
transactions, and retry timing are implementation/infrastructure concerns unless
they change a domain-visible guarantee.

No new primitive is required.

### 5.2. Policies and authorization abstractions — sufficient, with identity cost

State-based policies are a strong fit:

- `Unreachable(forbidden_decision)` checks non-bypass;
- `Reachable(allowed_decision)` prevents an over-restrictive model;
- principals/resources/roles can be scoped entities and params;
- provenance and separation-of-duty facts are finite relations.

The identity cost is real: introducing "who performed the latest action" adds
state and multiplies the graph. Research/30's proposed scope-key expression
removes plumbing but does not change verification power.

No authorization-specific primitive or policy sublanguage is required.

### 5.3. Games and narrative mechanics — sufficient for bounded mechanics

Supported:

- locations, inventory flags, resource counters, NPC/item slots;
- player choices as enabled actions;
- reachable endings/content;
- impossible endings;
- conservation/range rules;
- softlock detection and executable play through the transition kernel.

Not part of the model:

- prose and dialogue content;
- weighted randomness;
- continuous simulation/balance metrics;
- open-world scale.

The current claim should be "bounded game and narrative mechanics", not "model
an entire game." Within that claim, no new primitive is required.

### 5.4. Bounded protocols/controllers — sufficient for safety, not liveness

OAuth and Kubernetes establish that the DSL handles:

- multiple identities and resources;
- competing actors/controllers;
- ownership/provenance;
- bounded resource creation/deletion;
- all action interleavings at the declared atomic granularity;
- safety and recovery questions.

It does not establish:

- eventual controller convergence;
- fair scheduling;
- asynchronous queue semantics;
- network reorder/duplication unless explicitly represented as bounded state;
- races inside an atomic action.

Documentation must say "bounded safety/reachability abstraction", not
"distributed protocol verification" without qualification.

No new primitive is required for the qualified claim.

---

## 6. Adversarial requirement audit

The fastest way to catch scope inflation is to ask whether plausible sentences
mean what the current query actually proves.

| Requirement | Current status | Correct treatment |
|---|---|---|
| Balance is never negative | directly supported | `Invariant` / `AlwaysHolds` |
| A forbidden token is never issued | directly supported | `Unreachable` |
| A valid purchase path exists | directly supported | `Reachable` |
| From every reachable order state, settlement is still possible | directly supported | `NoDeadEnd(goal=settled)` |
| Every order execution eventually settles | **not supported** | liveness/fairness; do not relabel `NoDeadEnd` |
| Every emitted event is eventually handled | **not supported** | needs event state plus liveness/dispatch assumptions |
| A message is delivered within 30 seconds | **not supported as real time** | finite clock abstraction can check a bounded model only |
| Retry succeeds with probability ≥ 99.9% | **not supported** | probabilistic model checking/simulation |
| The system works for any number of users/orders | **not supported** | verification is within declared finite scopes |
| No race exists inside a database transaction | **not supported at that granularity** | split the protocol into read/write actions or use another tool |
| Every finite queue ordering is safe up to capacity N | encodable | explicit bounded queue state; may be verbose/large |
| Approval happened after the latest push | encodable | store revision/history facts in state |
| A collection may grow and shrink up to N objects | directly supported | scope presence + `Create`/`Delete` |
| A relation links many users to many resources | encodable | scoped relation/edge entities |
| An extension refines an imported action in place | behaviour encodable, modular refinement absent | integrate the model; overlay syntax is authoring/composition work |
| The implementation conforms to the model | **not supported** | future MBT/runtime bridge, separate from DSL expressiveness |

### 6.1. The important false friend: `NoDeadEnd`

For a goal set `G`, `NoDeadEnd(goal=G)` checks:

```text
for every reachable state s, some path from s reaches G
```

It does not check:

```text
every infinite execution from s eventually reaches G
```

An execution may keep choosing a self-loop or an unrelated enabled action
forever while the goal remains available. The first statement is recoverability;
the second is liveness under scheduling/fairness assumptions.

Consequences:

- `saga_always_settles` is a misleading identifier;
- "every run must terminate", "always settles", and "proves the process can
  never wedge" overstate the theorem unless "wedge" is explicitly defined as
  "no path to settlement remains";
- the accurate wording is "settlement remains reachable from every reachable
  state" or "the model has no settlement softlock."

This is a claims/documentation defect, not an engine false-green: the
`NoDeadEnd` implementation and README status boundary already describe the
weaker semantics.

---

## 7. Features considered and rejected as unnecessary

### 7.1. First-class nondeterministic outcomes

Not needed for verification power. Multiple actions/bindings already generate
the same graph. Add only if repeated authoring evidence shows that domain readers
need one family label and the current split damages reviewability.

### 7.2. Conditional effects

Not needed for verification power. Split guarded actions preserve semantics and
make branches explicit. Reconsider only as syntax sugar after measuring repeated
duplication.

### 7.3. Computed fields

Named expressions and aggregates already express derived values without adding
state. A first-class `Computed` field is useful only if authors need derived
values in generated schemas/introspection or need one reusable expression to
look like a field. That is tooling/ergonomics, not semantic closure.

### 7.4. Event pool and automatic dispatch

Not required by the target state-protocol abstraction. Domain causality is
currently represented in persistent state; `emits` is an observable output.

An event pool becomes justified only when an external model's correctness
depends on bounded pending-event multiplicity, consumption/broadcast semantics,
duplication/reordering, or payload-triggered transitions that cannot be honestly
reduced to state. Such a model will also need explicit queue bounds. Neither
external evidence model required it.

### 7.5. Time primitives

Finite logical time is already encodable as counters and tick actions. A native
clock would not solve fairness, dense/continuous time, or state explosion. Add
time only with a specific semantic target and verifier strategy.

### 7.6. Temporal/liveness queries

Do not add a friendly `Eventually(...)` name on top of the current BFS. That
would be a false promise. Real liveness requires path semantics, cycles,
fairness/stuttering decisions, and different counterexamples.

Quint explicitly separates state/action/run/temporal modes and provides
`always`, `eventually`, and fairness operators. That is evidence that temporal
semantics is a substantial language layer, not one more query constructor:

- https://quint.sh/docs/lang

If repeated real requirements make liveness central, the honest options are a
deliberate temporal phase or recommending/exporting to a temporal verifier—not
silently weakening the property.

### 7.7. Unbounded/dynamic collections

They would invalidate exhaustive explicit-state enumeration in the general case.
The fixed `Scope` universe is not a missing implementation detail; it is the
finiteness contract. Alloy similarly makes finite scopes a central analysis
boundary:

- https://alloytools.org/tutorials/online/maintext-FS-1.html

Larger scopes, symmetry reduction, symbolic backends, or abstractions are engine
scaling strategies. They do not change the first-release semantic contract.

### 7.8. General records, maps, lists, and recursive data

They improve authoring density but expand state encoding, equality, domain
inference, and artifact stability. Finite instances of these structures can
already be normalized into scopes, fields, presence, and relations.

Quint natively includes sets, maps, records, tuples, lists, sum types, temporal
operators, and nondeterministic choice. Matching that vocabulary would abandon
analint's constrained domain-contract niche:

- https://quint.sh/docs/lang

Do not add general collection types without repeated models whose normalized
form is unreadable or impractical.

---

## 8. Remaining gaps classified correctly

### 8.1. Pre-documentation API cleanup — required

Research/30 remains valid:

- remove semantic-looking metadata/non-executable modes;
- simplify boolean predicates, checkpoints, and lifecycle syntax;
- expose scope identity as a value;
- make canonical scope presence explicit;
- version machine-facing JSON contracts.

These changes improve semantic honesty and authoring density. They do not expand
the class of systems the verifier can represent.

### 8.2. Documentation claim corrections — required

Before publication:

- replace "always settles"/"every run terminates" with recoverability language;
- reserve "eventually" for explicitly unsupported liveness;
- qualify protocol/controller claims with "bounded safety/reachability";
- qualify game claims with "mechanics" and finite scopes;
- state that PASS is exhaustive only for a complete declared finite model;
- state that model fidelity is the author's abstraction responsibility.

### 8.3. Tooling and product gaps — not DSL expressiveness

Useful future work that does not block semantic closure:

- implementation/trace conformance;
- semantic diff;
- generated prose/decision-table views;
- better model mining;
- visualization;
- reductions and performance;
- more compact identity/relation authoring;
- richer diagnostics for abstraction and unbounded-domain risks.

### 8.4. Genuine out-of-scope semantics — no action now

- liveness/fairness;
- real asynchronous event delivery;
- real time;
- probability;
- unbounded structures;
- intra-action concurrency.

These should remain explicit non-goals until repeated external evidence changes
the product scope.

---

## 9. Release gate

The DSL is semantically ready for documentation when all of the following hold:

1. research/30's bounded API cleanup is implemented;
2. `NoDeadEnd` claims are corrected across examples and docs;
3. docs define the finite abstraction and completeness contract;
4. docs distinguish recoverability from inevitability;
5. docs list the out-of-scope semantics in §8.4;
6. example intent and characterization tests remain green;
7. no new semantic primitive is added merely to make examples shorter.

The release does **not** need:

- temporal logic;
- event dispatch;
- conditional effects;
- general collections;
- `Computed`;
- a second verifier/backend;
- an implementation bridge.

---

## 10. Final decision

The project has reached **semantic closure for its chosen first-release scope**.

It has not reached universal product-goal closure: external usability,
long-term maintenance economics, adoption, and implementation conformance remain
open evidence/tooling questions.

That does not mean analint can describe every real system at full fidelity. No
bounded domain verifier can. It means:

- every target model can be reduced to a finite state-transition abstraction;
- the current DSL can represent that abstraction;
- the current engine can answer the target safety/reachability questions;
- unsupported questions have a clear semantic boundary;
- current evidence does not justify another primitive.

Proceed with the API cleanup from research/30 and documentation. Reopen
expressiveness only when a real model produces a requirement that is both:

1. inside the stated product scope; and
2. not honestly encodable with current finite-state primitives without losing
   the property being claimed.

Until then, another language feature would be speculation.
