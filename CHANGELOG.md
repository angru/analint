# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is
`0.x` the public API may change between minor releases.

## [Unreleased]

### Added

- **Property slicing** (research/34 §5): `check` verifies every invariant and
  query on its cone of influence instead of the whole model. Specs with
  independent processes no longer pay for the product of all of them. The
  result is exact: a conformance test pins it against the whole-model path on
  every example. JSON reports each check's `slice`; `check --no-slice` (MCP
  `slice=false`) restores whole-model exploration.
- Slices skip writers that only switch a flag off (a spent one-time code, a
  closed profile): processes that share such a flag no longer join each
  other's slices. Exact; NoDeadEnd and properties reading the flag keep them.
- `check --max-states N` (MCP `max_states`) overrides every exploration budget
  for one run.
- Warning for a behaviour object defined in a spec module but not part of the
  model.
- `examples/broker`: a generic retail broker (verification, trading accounts,
  payments) as one `Contract` per process — the scaling benchmark.

### Changed

- **Breaking (research/35 step 4):** the model is exactly what `Spec` and its
  imported `Contract`s list. Module globals are no longer scanned for
  membership, and there is no per-field mixed mode; entities, events, scopes
  and inline lifecycles are derived from the behaviour that references them.
  A `Spec` that lists no behaviour is an "empty model" error, and a defined
  but unlisted action, invariant, scenario, flow or query is reported as an
  orphan. Migrate with `Spec(..., actions=[...], scenarios=[...], ...)` or one
  `Contract` per process. `--what-if` still merges its file's objects.

- The summary separates budget-exhausted invariants (`inconclusive`) from
  invariants that could not be checked at all (`not checked`). JSON adds
  `invariants_inconclusive` and `invariants_not_checked`;
  `invariants_unchecked` remains their sum.
- Explored states take 8–15× less memory: a state is a compact key, and its
  context is rebuilt on demand (research/36 R4).
- Exploration is about 5× faster on whole-model runs (shared canonical
  exploration, copy-on-write effects, cached guard plans and state layout).

### Fixed

- A parameterized action without an explicit `id` composed through
  `Contract` + `Spec(imports=...)` kept empty instance ids.

## [0.0.1] — 2026-06-21

First public release. The engine and CLI are mature and covered by an extensive
test suite; this release makes them installable and documents their scope.

### Added

- **DSL** for declaring system behaviour in Python: `Entity` with field
  constraints, `Invariant`, `Action` (`pre` / `effect` / `post` / `emits`),
  `Event`, `Lifecycle`, `Scenario`, `Flow`, parameterized actions
  (`Param`), finite quantifiers/aggregates, `Scope` multiplicity, and `Spec` as
  the top-level aggregate.
- **Validator** with a single transition kernel shared by scenarios, flows, and
  the explorer; structural validation; scenario execution; executable multi-step
  flows.
- **Bounded reachability engine**: BFS over a finite state graph with reachability
  queries (`Reachable`, `Unreachable`, `AlwaysHolds`, `NoDeadEnd`, `DeadActions`),
  state-diff witness/counterexample traces, and a deterministic
  `analint.exploration/v1` artifact.
- **CLI** `analint`: `check`, `show`, `affects`, `explore`, `trace`, with
  `--what-if` hypothesis testing, terminal and JSON output, and meaningful exit
  codes.
- **MCP server** (`analint-mcp`, optional `mcp` extra) exposing the same surface
  to AI agents.
- **Examples** spanning business analytics, game/narrative rules, and two external
  evidence models (GitHub branch protection, OAuth 2.0 auth-code + PKCE), plus a
  project-sized Kubernetes ReplicaSet dogfood.

### Scope and honesty

- Verification is **bounded reachability** over a finite state space: it checks
  safety and reachability and reports a three-valued verdict
  (`PASS` / `FAIL` / `INCONCLUSIVE`), preferring `INCONCLUSIVE` / `NOT_CHECKED`
  over a silent pass.
- It deliberately does **not** model liveness or temporal "eventually"
  properties. This is a scope boundary, not a defect.

[0.0.1]: https://github.com/angru/analint/releases/tag/v0.0.1
