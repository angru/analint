# analint

**Declare how a system behaves in Python, then check its consistency.**

Describe state with entities, transitions with actions, and relationships with
invariants. Run concrete scenarios or explore the reachable states to find a
counterexample you did not think to write as a test.

```bash
pip install analint
analint check path/to/spec/
```

Requires Python 3.12 or newer. The latest released version is **0.0.2**; this site
tracks the repository's main branch. Features marked **unreleased**, including
`check --cache`, require a source checkout until the next release. For development:

```bash
git clone https://github.com/angru/analint
cd analint
uv sync --frozen
uv run analint check examples/cloak/
```

## Start with a small model

The [first-spec tutorial](getting-started.md) builds a ticket workflow with three
reachable states. You will check a successful transition, an intentionally blocked
transition, a complete journey and a reachability property, then introduce a defect
and read its counterexample.

| Your next step | Read |
| --- | --- |
| Understand what a PASS proves | [Verification concepts](concepts.md) |
| Look up a declaration or semantic rule | [DSL reference](dsl.md) |
| Run checks, inspect a model or read JSON | [CLI reference](cli.md) |
| Give a coding agent the workflow or connect MCP | [For AI agents](agents.md) |
| Learn from a larger working model | [Examples gallery](examples.md) |

## What the checker establishes

analint checks the **model you declare**: its state domains, actions, guards and
initial states. A complete exploration can prove safety and reachability within
that model. It does not verify that application code implements the specification,
and `NoDeadEnd` establishes that a goal remains reachable rather than that every
execution eventually reaches it.

Results distinguish **PASS**, **FAIL** and **INCONCLUSIVE**. A budget-exhausted
check cannot silently become a pass. Individual properties can also be
**NOT_CHECKED** when they could not be evaluated. See
[verdicts and completeness](concepts.md#verdicts-and-completeness) before using the
checker as a CI gate.

The project is an early public release; pin a version if you depend on its API.
Development and release history live in the
[roadmap](https://github.com/angru/analint/blob/main/ROADMAP.md) and
[changelog](https://github.com/angru/analint/blob/main/CHANGELOG.md).
