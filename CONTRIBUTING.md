# Contributing to analint

Thanks for your interest in analint. This checkout targets `0.2.0`:
issues, reproductions, and example specs are especially welcome.

All new repository content — code, comments, docs, commit messages — is written in
**English**. (Some historical research notes are in Russian; leave them as-is.)

## Development setup

analint uses [uv](https://docs.astral.sh/uv/) and targets **Python 3.12+**.
CI tests Python 3.12–3.15, including clean wheel/MCP installations and source
archive collection on each version.

```bash
git clone https://github.com/angru/analint
cd analint
uv sync                      # create the env and install dev dependencies
uv run analint examples/ecommerce/   # smoke test
```

## Running the checks

```bash
uv run pytest                # full test suite
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run ty check              # type check (src/)
```

CI also runs a separate **TLC conformance** job with Temurin Java 17 and the
official TLA+ 1.7.4 JAR, verified against its pinned SHA-256. Its preflight fails
if Java or the JAR is unavailable; unsupported model exports may still skip
individual cases. To run the same suite locally, set `ANALINT_TLC_JAR` to a
local `tla2tools.jar` and run:

```bash
uv run python -c "from analint.backends.tlc import find_tlc; print(find_tlc())"
uv run pytest -q -rs tests/test_tlc_backend.py tests/test_fixed_initial.py \
  tests/test_initial_presence.py tests/test_keys.py
```

A few specific things to know about the test suite:

- `tests/test_characterization.py` is the behavioural regression oracle: a
  committed golden snapshot (`tests/snapshots/examples.json`) of every example's
  verdict, per-scenario results, and per-query graph hashes/traces. If you
  **intentionally** change behaviour, regenerate it — never mechanically, always
  after confirming the new snapshot is correct:

  ```bash
  UPDATE_SNAPSHOT=1 uv run pytest tests/test_characterization.py
  ```

  See `tests/snapshots/README.md` for the regen rule and expected deltas.
- `tests/test_transition_conformance.py` is the fine-grained kernel gate. It
  checks agreed transition semantics directly; the historical target changes
  have been resolved and no strict-xfail placeholders remain.

## Extending the AST

`tests/test_ast_coverage.py` is the executable node inventory. It discovers
concrete `Symbolic` and `Effect` subclasses and requires a representative case
for each (excluding the explicit abstract bases). Bound variables, scopes,
instance identities and parameter substitution have authoring-leaf probes.
Adding a node requires a decision in every applicable column:

| Node family | Structural references | Slicing / impact | Interpreter / compiler | Cache | TLA export |
| --- | --- | --- | --- | --- | --- |
| Comparisons, boolean/null/membership predicates | All operand fields | All operand reads | Evaluate both paths | Explicit schema | Render |
| ForAll / Exists / Present | Bound fields; presence has no field reference | Include slot presence | Present members only | Explicit schema | Render with presence guards |
| Arithmetic / Key / Count / Sum | Fields; Key reads no state | Fields and aggregate membership | Evaluate both paths | Explicit schema | Render |
| Min / Max | Bound fields | Fields and membership | Empty scope raises | Explicit schema | Refuse |
| Set / Add / Subtract / Create / Delete | Targets and RHS checked | Reads, writes and presence guards | Transition kernel (existing conformance suite) | Explicit schema | Render |
| Param / ParamField / BoundField | Substitute or bind before execution | Reject unbound runtime reads | Binding required | Params refused; bound schemas recorded | Refuse unbound operands |

Reference collectors are helpers for structurally validated trees, not validators.
Unknown predicates/operands must be rejected at structural validation and runtime;
slicing must fall back to the whole model. Impact analysis refuses unknown reads
or effects, returning the same structured error to Python, CLI and MCP callers
(CLI exit 1), with guidance to run `analint check`. Dependency-bearing `show`
requests use the same error boundary; the overview remains inspectable.
Cache encoding only accepts audited dataclass schemas; an unknown
schema bypasses the cache. TLA export refuses unknown nodes/effects. Do not add a
catch-all that treats arbitrary Python objects as literals or drops unknown effects.

The operand literal domain is explicit: `None`, `bool`, `int`, `float`, `str`,
`Enum`, and `InstanceRef`. Declared `Entity` classes also remain valid identities
for parameter filters such as `where=[src != dst]`; arbitrary Python classes
are not literals. Plain dataclasses, containers, callbacks and entity snapshots
in operand position are structural errors even if they do not inherit `Symbolic`.
This boundary is shared by native structural validation, evaluation and slicing;
backend rendering remains independently checked.

`tests/test_generated_conformance.py` adds 24 fixed-seed tiny singleton models
and eight scoped cases. It compares sliced/whole verdicts and witness lengths,
interpreted/compiled values and exceptions, and full cold/warm/fresh JSON reports
(excluding timing) for the singleton models. It proves cache hits and exercises
smaller slices, with both valid models and planted invariant/payload defects.
The bounded corpus runs in seconds; it is not exhaustive model generation.
NoDeadEnd's documented out-of-slice illegal-state divergence is outside this
corpus. Keep the example snapshots and independent TLC conformance gates: a
shared implementation bug can fool differential tests.

No shared visitor framework is required. Inventory failures should first produce
a narrow semantic fix; consolidate walkers only when a concrete duplication cost
justifies coupling them.

## Trying the CLI

```bash
uv run analint check .                      # validate the spec in the cwd
uv run analint show action <id> -p <spec>   # inspect one action
uv run analint affects <Entity.field> -p <spec>   # blast radius of a field
uv run analint explore <spec>               # bounded reachability exploration
uv run analint check . --what-if file.py    # test a hypothesis without editing files
```

Exit codes: `0` ok · `1` findings · `2` usage · `3` spec failed to load · `4`
inconclusive (a query exhausted its exploration budget — it proved nothing). JSON
output carries a three-valued `verdict` (`PASS`/`FAIL`/`INCONCLUSIVE`).

## Documentation

The MkDocs site lives in `docs/`; navigation is defined in `mkdocs.yml`.
It tracks main, so mark unreleased features explicitly. Runnable tutorial
blocks are executed directly from the Markdown by the documentation tests,
including a planted defect and a packaged `--what-if` hypothesis.

```bash
uv run --frozen pytest tests/test_documentation.py \
  tests/test_fixed_initial.py::test_fixed_roots_across_check_explore_and_trace \
  tests/test_keys.py::test_key_verdicts_traces_artifacts_and_cache_agree
uv run --frozen --group docs mkdocs build --strict
uv run --frozen --group docs mkdocs serve
```

The docs workflow builds strictly and runs these tests on pull requests and
main-branch pushes. Deployment runs only on main after validation succeeds.
Keep CLI/MCP examples consistent with their implemented argument sets, preserve
the bounded-verification assumptions, and link new pages from the navigation.

## Release acceptance

Build one wheel/source pair in a clean output directory, then run the same gate
used by both Quality CI and the publishing workflow:

```bash
uv build --out-dir /tmp/analint-dist
uv run --no-project python -I scripts/check_release.py --dist-dir /tmp/analint-dist
```

`--python 3.15` selects another interpreter for the temporary environment.
`--expected-version v0.0.5` checks a release tag explicitly; the default is the
checkout's package version. Mixed versions, extra stale artifacts and a tag
that disagrees with distribution metadata fail before installation.

The gate installs the wheel without dev dependencies and checks CLI version,
PASS/FAIL/INCONCLUSIVE exit codes and JSON, what-if isolation, cold/warm cache
parity, traces and Create impact. It then installs the MCP extra and starts
`analint-mcp` over stdio, initializes a client and calls all five tools. Only
after those checks does it add test tools, run strict Twine validation, collect
the extracted archive's tests and execute the focused documentation, impact,
diagnostic code, inspection, initial-state/key and release-acceptance cases
against the installed wheel.
The fulfillment trial also compares semantic results with its committed JSON
record, included in the source archive. Intentional verdict/state-count changes
require reviewing and updating that record and the examples guide together.
The final JSON records the verified version and distribution SHA-256 values.

Publishing builds artifacts once and verifies those same files on Python
3.12–3.15 before either registry job can run. A GitHub Release also checks its
tag against the artifact version. To exercise the complete publishing gate
without a registry upload, dispatch Publish with `verify_only=true`:

```bash
gh workflow run publish.yml -f verify_only=true
```

The default manual run retains the TestPyPI dry run; published GitHub Releases
use PyPI. Both paths require the verification matrix to succeed.

## How the project works

- **`ROADMAP.md` is the single source of truth** for status and priorities.
  `research/` holds dated design rationale that the roadmap links to;
  `AGENTS.md` is a detailed map of the codebase.
- The project is **review-gated and fail-closed by design**: a verification
  feature that hides a defect is the worst possible outcome here. Prefer
  `INCONCLUSIVE` / `NOT_CHECKED` over a silent pass. When you add or change a
  verification path, adversarially self-probe it — plant a defect the new path
  should catch and confirm the overall verdict actually goes `FAIL`.
- Keep changes semantically focused: one behavioural change per commit, with the
  characterization snapshot updated deliberately in the same commit.

## Pull requests

1. Branch from `main`.
2. Make the change; add or update tests and (if behaviour changed) the snapshot.
3. Ensure `pytest`, `ruff`, and `ty` are green.
4. Open a PR describing **what guarantee changed**, not just the diff.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
