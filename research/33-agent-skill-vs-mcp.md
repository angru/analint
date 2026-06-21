# Agent Skill vs MCP for analint

**Date:** 2026-06-21

## Question

Should analint provide an Agent Skill or plugin so coding agents can model
systems without requiring users to configure the existing MCP server?

## Decision

Add one portable Agent Skill, but do not replace MCP.

The product layers have different jobs:

| Layer | Responsibility |
|---|---|
| Python library and CLI | The executable source of truth |
| Agent Skill | Teach an agent when and how to use analint |
| MCP server | Expose typed operations and structured results |
| Product-specific plugin | Optional distribution wrapper for skills and MCP configuration |

For local coding agents with shell access, `analint` plus a skill should be the
default path. MCP remains the stronger optional integration for clients that
benefit from typed tool discovery or do not expose a normal shell.

## Why the current MCP surface is still useful

The existing server is a thin adapter over the same implementation as the CLI.
It exposes five operations:

- `show` for orientation;
- `affects` for impact analysis;
- `check` for validation and `what_if` hypotheses;
- `explore` for bounded reachability artifacts;
- `trace` for witnesses and counterexamples.

This is not redundant product logic. Machine-facing results have versioned
schemas, and exploration has compact defaults and explicit graph-size guards.
MCP therefore provides properties that prose instructions cannot enforce:
typed arguments, discoverable operations, structured return values, and
programmatic limits.

Its cost is installation and client configuration:

```text
pip install "analint[mcp]"
configure analint-mcp in the agent client
```

For an agent that can already run `analint ... --format json`, that setup often
adds transport without adding capability.

## What a skill adds

MCP tool descriptions explain individual calls. They do not reliably teach the
workflow or the DSL's semantic constraints.

A skill can encode the intended loop:

```text
show -> affects -> what-if -> apply -> check
                         \-> explore / trace when reachability matters
```

It can also teach the agent to:

- locate and understand an analint specification before grepping files;
- distinguish `FAIL`, `INCONCLUSIVE`, and `NOT_CHECKED`;
- treat effects as simultaneous facts evaluated against the pre-state;
- use `Scope`, `Param`, quantifiers, presence, and `Initial` correctly;
- avoid removed wrappers and host-language factories for model families;
- inspect examples and focused references only when needed.

This addresses the main agent failure mode for a DSL: not inability to reason
about invariants and transitions, but invented syntax and incorrect procedure.
The validator catches the former only after the agent has chosen to invoke it;
the skill tells the agent when and how to do so.

## Ecosystem evidence

Agent Skills is now an open `SKILL.md` format rather than a Claude-only
convention. Codex, Claude Code, and GitHub Copilot document support for the
format. Skills use progressive disclosure: clients initially load metadata,
then read the instructions and references only when relevant.

This makes a skill more portable than a product-specific plugin. Plugins remain
useful distribution units:

- Codex describes skills as the reusable workflow format and plugins as the
  installable package for skills and app integrations;
- Claude Code plugins can bundle skills, agents, hooks, and MCP servers;
- GitHub Copilot can install standalone skills directly from repositories.

FizzBee is a close precedent. It distributes skills that teach agents to write
specifications, run the model checker, debug failures, and create model-based
tests. That validates the category, but analint should not copy its four-skill
split before one skill proves too broad.

## Recommended first version

Ship one instruction-only skill named `analint`.

Its `SKILL.md` should contain:

1. precise activation conditions;
2. the canonical workflow;
3. commands for `show`, `affects`, `check`, `explore`, and `trace`;
4. verdict and exit-code interpretation;
5. the small set of semantic traps listed above;
6. links to focused DSL references and examples.

Do not bundle scripts initially. The CLI already owns execution, validation,
JSON output, and error handling. A script wrapper would duplicate it.

Keep detailed DSL material in referenced files so the main skill remains small.
The skill and package documentation must name the supported analint version or
schema generation so stale instructions are detectable.

Before distribution, evaluate three representative tasks:

1. modify an action after using `affects`;
2. test a new invariant through `--what-if`;
3. inspect exploration output and report `INCONCLUSIVE` honestly.

## Distribution sequence

1. Add the portable skill to the analint repository and test it locally.
2. Document manual installation into a standard skills directory.
3. Add a minimal installer only if copying the directory is repeated friction.
4. Package it as product-specific plugins only when marketplace distribution or
   automatic MCP configuration has a real consumer.

The intended entry points become:

```text
pip install analint
install the analint skill
```

and, optionally:

```text
pip install "analint[mcp]"
```

## Risks and boundaries

- A skill is operational prompt text, not a typed protocol. Agents may ignore or
  misapply it; validation remains mandatory.
- Skill instructions can drift from the DSL. Keep them versioned and verify them
  against executable examples.
- Third-party skills and bundled scripts are a supply-chain boundary. The first
  analint skill should avoid scripts and broad pre-approved shell permissions.
- Different clients use different installation and plugin conventions despite
  sharing `SKILL.md`. Keep the core skill portable and packaging thin.
- A skill improves authoring reliability but does not solve spec-to-code drift.
  The conformance problem identified in research/08 and research/11 remains.

## Current documentation defects found during the review

- `README.md` says MCP exposes three tools, while the server exposes five.
- The MCP `show` docstring still lists the removed `actor` kind.

These are documentation fixes, not arguments against the architecture.

## Sources

- Agent Skills overview and specification:
  <https://agentskills.io/home>,
  <https://agentskills.io/specification>
- OpenAI Codex Agent Skills:
  <https://developers.openai.com/codex/skills>
- Claude Code skills and plugins:
  <https://code.claude.com/docs/en/skills>,
  <https://code.claude.com/docs/en/plugins>
- GitHub Copilot Agent Skills:
  <https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills>
- Model Context Protocol architecture:
  <https://modelcontextprotocol.io/docs/learn/architecture>
- FizzBee's agent skills:
  <https://github.com/fizzbee-io/fizzbee#ai-coding-assistant-skills>
