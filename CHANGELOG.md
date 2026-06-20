# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is
`0.x` the public API may change between minor releases.

## [0.0.1] — 2026-06-19

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
