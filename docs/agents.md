# For AI agents

analint is built for coding agents as first-class users: every command speaks
JSON with a versioned `schema`, and the model is inspectable without reading
source. There are two ways to give an agent that surface.

This page documents the repository's main branch. `cache` is available since
**0.0.3**; the other listed MCP operations are available since 0.0.2. The
[CLI reference](cli.md) covers terminal options, which are not identical to the
MCP argument set.

## Agent Skill (recommended)

The repository ships a portable [Agent Skill](https://agentskills.io/) at
[`skills/analint/`](https://github.com/angru/analint/tree/main/skills/analint).
A skill is a plain `SKILL.md` that teaches an agent **when and how** to use
analint: the `show → affects → what-if → apply → check` loop, fail-closed verdict
interpretation, and the DSL's semantic rules (effects are simultaneous facts,
where to put `Field`/`Invariant`/`Lifecycle`, `Scope`/`Param`/presence, the loader
contract). It carries no scripts — the CLI already owns execution.

`SKILL.md` is an open format read natively by **Claude Code**, **Codex**, and
**GitHub Copilot**; **Antigravity** and other agents that scan a `skills/`
directory pick it up the same way.

**Install** — copy the skill into the agent's skills directory:

```bash
# Claude Code: project-local or global
cp -r skills/analint .claude/skills/analint
# or  ~/.claude/skills/analint

# Codex / Antigravity: into that agent's skills directory
```

The agent also needs `analint` on `PATH`:

```bash
pip install analint        # or: uv add analint
```

Then drive it in plain language — *"use analint to check this spec before
editing"* — and the skill supplies the workflow.

## MCP server (optional)

For clients that prefer typed tool discovery over a shell, the same core is
exposed as an MCP server with five tools — `check`, `show`, `affects`, `explore`,
`trace`:

```bash
pip install "analint[mcp]"   # then configure `analint-mcp` in the client
```

Use MCP when the client benefits from discoverable, typed operations or has no
normal shell; otherwise the CLI plus the skill is the lighter path.

Configure a local stdio server in your client's MCP settings with executable
`analint-mcp` and no arguments. The process must have access to the spec files
and its required Python imports. The exact settings-file format belongs to the
client. Paths are resolved on the machine running the server; use absolute paths
when the client's working directory is uncertain.

### Tool reference

All five tools return structured dictionaries. Optional arguments and defaults
below match the server's tool definitions.

| Tool | Required arguments | Optional arguments |
| --- | --- | --- |
| `check` | None | `path="."`, `what_if=null`, `max_states=null`, `slice=true`, `tlc=false`, `cache=false` (cache since 0.0.3) |
| `show` | None | `path="."`, `kind=null`, `name=null` |
| `affects` | `target` | `path="."` |
| `explore` | None | `path="."`, `query=null`, `what_if=null`, `include_graph=false`, `max_graph_states=null` |
| `trace` | A property id in `query` for a useful request | `path="."`, `query=""`, `what_if=null`, `slice=true` |

`check` runs the full validation pipeline. `max_states` overrides every
exploration budget and must be positive; `slice=false` corresponds to CLI
`--no-slice`. `tlc=true` tries the supported TLC fallback for INCONCLUSIVE
properties. MCP currently exposes no `strict`, scenario/tag filtering or
`tlc_timeout` parameter; use the CLI when those options are needed.

`show` returns an overview without a kind, an id list with just a kind, and
details with a kind/name pair. Detailed kinds are entity, event, invariant,
action, lifecycle, flow, scenario and contract. `affects` accepts a field,
entity/event name or action id.

`explore` follows the whole model for canonical or query-specific roots. It
returns a compact artifact by default. To request the graph, supply both
`include_graph=true` and `max_graph_states=N`; the latter caps **output**, not
exploration. Above that graph size, the response retains the summary and explains
why `graph` is null. Read `completeness` separately.

`trace` accepts an invariant id as well as a query id, despite the argument's
name. It follows the same slice and budget decisions as `check`. A property
without a witness returns `witness: null` with an explanation.

For example, send these arguments to `check`:

```json
{
  "path": "/absolute/path/to/ticket_spec",
  "max_states": 10000,
  "slice": true
}
```

Then inspect the witness by passing this to `trace`:

```json
{
  "path": "/absolute/path/to/ticket_spec",
  "query": "can_archive"
}
```

### Workflow and verdicts

1. `show` the inventory, then inspect the relevant action or contract.
2. Use `affects` before changing a field or transition.
3. Test a proposed property through `check(what_if=...)` using the same packaged
   entity imports as the model.
4. Apply the accepted change and list its behaviour on Spec or Contract.
5. Run `check` again and read the overall verdict and per-property findings.

The check response uses `analint.check/v1`. Treat only `verdict: "PASS"` and
`passed: true` as success; FAIL, INCONCLUSIVE and individual NOT_CHECKED results
require interpretation. Scenarios passing does not establish canonical
invariants. A retrieved trace is diagnostic evidence, not a substitute for the
full report. See [verification concepts](concepts.md).

### JSON schema identifiers

| Response | Schema |
| --- | --- |
| Validation report | `analint.check/v1` |
| Model inventory | `analint.overview/v1` |
| Detailed object or id list | `analint.show/v1` |
| Impact analysis | `analint.affects/v1` |
| Exploration artifact | `analint.exploration/v1` |
| Witness/counterexample | `analint.trace/v1` |
| Operation error, where supported | `analint.error/v1` |

Inspect error fields as well as schemas. Some lookup errors retain the
operation's schema. Invariant traces identify the property with `invariant`
instead of `query`; clients should accept both forms.

## Which to use

| Layer | Job |
|---|---|
| `analint` CLI / library | the executable source of truth |
| Agent Skill | teaches an agent *when and how* to use analint |
| MCP server | typed, discoverable operations with structured results |

The skill and the JSON schemas are versioned (`analint.check/v1`,
`analint.show/v1`, `analint.exploration/v1`, …) so an agent can detect stale
instructions. Validation is always mandatory: a skill is prompt text, not a typed
guarantee.
