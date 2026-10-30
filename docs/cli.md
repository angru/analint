# CLI reference

The examples below use the [tutorial model](getting-started.md). Replace `.`
with a directory containing `spec.py` or the path to an entry-point Python file.
Run `analint --help` or `analint COMMAND --help` for installed-version options.

## check

```bash
analint check .
analint .                         # shorthand
analint check . --format json
analint check . --strict
```

Checks loading and structure, scenarios, flows, canonical invariants and queries.
The overall verdict includes all of these stages.

| Option | Meaning |
| --- | --- |
| `-f, --format terminal\|json` | Select human-readable or JSON output |
| `-s, --scenario ID` | Filter scenarios by id; repeat for multiple ids |
| `-t, --tag TAG` | Filter scenarios by tag; repeat for multiple tags |
| `--strict` | Warnings fail the run |
| `--what-if FILE.py` | Merge hypothesis objects for this invocation |
| `--max-states N` | Override canonical and query budgets with a positive integer |
| `--no-slice` | Use whole-model exploration instead of property slices |
| `--tlc` | Hand supported INCONCLUSIVE properties to TLC |
| `--tlc-timeout SECONDS` | Timeout per exported TLC check, at least 1 second; default unlimited |
| `--cache` | Since 0.0.3: persist/reuse explorations of unchanged slices |

Scenario/tag filters select scenario execution; they do not turn the command
into a scenario-only validation that skips invariants, flows or queries.

The cache directory defaults to `~/.cache/analint`; set `ANALINT_CACHE_DIR` to
override it. Caching does not change findings or completeness. Timings measure
performed work, so a reused exploration is cheaper than a fresh one.

### JSON reports

`check --format json` returns `analint.check/v1`. Read `verdict` and `passed`
before inspecting individual results. `passed` is true only for an effective
PASS, including the effect of `--strict`.

| Field | Contents |
| --- | --- |
| `spec` | Root id and name |
| `load_errors`, `structural` | Load problems and structural findings |
| `scenarios`, `flows` | Example/journey results and findings |
| `invariants`, `queries` | Per-property status, state count, trace and findings |
| `exploration` | Findings encountered while exploring transitions |
| `summary` | Aggregated counts, including inconclusive and unchecked invariants |

Property results can include `slice`, `elapsed_ms` and `backend: "tlc"`.
`elapsed_ms` measures incremental work for that property; shared exploration is
charged to its first consumer, and invariant retries are included. Model
preparation and shared action coverage are excluded. Summing these timings does
not give total command time.

## show

```bash
analint show -p .
analint show action -p .
analint show action resolve -p .
analint show entity Ticket -p .
analint show lifecycle Ticket.status -p .
```

`show [KIND] [NAME] --path PATH` always returns JSON. Without arguments it
returns the `analint.overview/v1` model inventory. With a kind it lists ids;
with a kind and name it returns details using `analint.show/v1`.

Detailed kinds are `entity`, `event`, `invariant`, `action`, `lifecycle`, `flow`,
`scenario` and `contract`. Query ids are available in the overview or
`show query`; use `trace QUERY_ID` for a property's witness.

## affects

```bash
analint affects Queue.open_tickets -p .
analint affects Ticket -p .
analint affects resolve -p .
```

`affects TARGET --path PATH` returns `analint.affects/v1`. Targets are fields
(`Entity.field`), entity/event names or action ids. Inspect readers, writers,
constraints and scenario coverage before changing the model.

## trace

```bash
analint trace can_archive -p .
analint trace can_archive -p . --format json
analint trace resolved_leaves_no_open_ticket -p .
```

`trace PROPERTY_ID --path PATH` returns a query witness or invariant
counterexample with state changes. Options are `--format terminal|json`,
`--what-if FILE.py` and `--no-slice`.

JSON uses `analint.trace/v1`, with `query` or `invariant` identifying the property,
its `status`, the root, `steps` and `final_state`. A property without a witness
returns `witness: null` and an explanation. The command follows `check`'s slice
and budget decisions; use `--no-slice` for the whole model. Adjust the model's
budget for a larger trace exploration; trace has no `--max-states` option.

Successful trace retrieval is an inspection operation. Its process exit code
does not replace the property's `status` or a `check` verdict.

## explore

```bash
analint explore .
analint explore . --format json
analint explore . --query can_archive --format json --include-graph
```

`explore [PATH]` explores the **whole model**, starting from canonical roots or
the roots of `--query ID`. It accepts `--what-if FILE.py` and
`--format terminal|json`. `--include-graph` includes the nodes and edges in JSON;
the default is a compact summary.

The `analint.exploration/v1` artifact includes `source`, `completeness`, `summary`,
`findings` and `graph`. `graph: null` can mean output was intentionally omitted;
it does not by itself mean the exploration was incomplete. Read `completeness`
separately. The artifact's content-derived node/edge ids are stable across
equivalent runs.

Like trace, explore is an inspection operation; use `check` as the CI verdict
gate. Explore does not have the check command's `--max-states`, `--cache`,
`--tlc` or `--no-slice` switches.

## Hypothesis workflow

Use the same shared entity classes in your hypothesis and spec. Packaged models
use qualified imports, as shown in the [tutorial](getting-started.md#test-a-proposed-rule-without-changing-the-model).

```bash
analint show -p path/to/spec
analint affects Entity.field -p path/to/spec
analint check path/to/spec --what-if hypothesis.py --format json
# Apply the accepted change to the spec, then check again.
analint check path/to/spec --strict
```

`--what-if` merges objects without editing the entry point or permanently
changing its cached root. After applying a hypothesis, list new behaviour on
Spec or an imported Contract; normal module imports do not register it.

## Exit codes

The following table applies to **check**:

| Code | Meaning |
| --- | --- |
| `0` | Effective PASS |
| `1` | FAIL: findings, failed scenarios/flows/properties, or strict warnings |
| `2` | CLI usage error, such as an invalid option or format |
| `3` | Spec failed to load or no root spec was found |
| `4` | INCONCLUSIVE, including an unchecked invariant preventing PASS |

For show, affects, trace and explore, a successful response means the inspection
operation ran; inspect the returned data to interpret verification results.
Machine-readable operation errors use `analint.error/v1` where supported.

## CI and local development

For an installed release, gate your spec with:

```bash
analint check path/to/spec --strict --format json
```

Pin the analint version and retain both the exit code and report. Do not turn
code `4` into success without an explicit policy for unresolved properties.

From a repository checkout, the documentation is checked with:

```bash
uv run --frozen pytest tests/test_documentation.py \
  tests/test_fixed_initial.py::test_fixed_roots_across_check_explore_and_trace \
  tests/test_keys.py::test_key_verdicts_traces_artifacts_and_cache_agree
uv run --frozen --group docs mkdocs build --strict
```

The docs workflow performs these checks for pull requests and main-branch
pushes before its main-branch-only deployment.
