# For AI agents

analint is built for coding agents as first-class users: every command speaks
JSON with a versioned `schema`, and the model is inspectable without reading
source. There are two ways to give an agent that surface.

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
