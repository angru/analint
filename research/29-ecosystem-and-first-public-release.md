# Ecosystem & first public release (0.0.1)

**Date:** 2026-06-19

The P4 self-contained workbench is complete (research/26, all checkpoints ✅) and
the evidence gate is passed (research/25): no new verification primitive is
demanded. Roadmap §"Deferred ecosystem work" gated publication explicitly on
workbench completion — that milestone is now reached, so this phase makes analint
installable and contributable without changing any semantics.

This is a packaging/positioning phase, **not** an engine change. No DSL, kernel,
explorer or artifact behavior is touched. Success = a stranger can
`pip install analint`, run `analint check`, read how to contribute, and the
published metadata is honest about maturity.

## Decisions (locked with the user, 2026-06-19)

- **License: MIT.** Simplest permissive license, dominant across Python tooling
  (ruff, pydantic). `LICENSE` file + `pyproject` `license`/classifier.
- **Version: 0.0.1.** The internal `1.0.1` tracked roadmap milestones (v0.9 →
  v1.0 → v1.0.1), not a public contract. A `0.x` first release is the honest
  signal that the public API is not yet frozen — consistent with the roadmap
  principle "do not publish before names stabilize". User chose `0.0.1` over the
  more conventional `0.1.0` as the maximally-cautious "very early" marker.
- **`requires-python`: relax `==3.14.*` → `>=3.12`.** The real language floor is
  PEP 695 type parameters (`class Lifecycle[S]:`, `class Transition[S]:` in
  `models/lifecycle.py`), introduced in 3.12. The exact-3.14 pin was an
  artifact, not a requirement; it would exclude almost every installer. **Floor
  change must be proven by running the suite under 3.12, not just asserted**
  (review-gated honesty) — this caught a PEP 758 use in `examples/play.py`.
  **Dev tooling must also drop to the support floor:** ruff `target-version` and
  ty `python-version` go `3.14 → 3.12`. With ruff on `py314`, `ruff format`
  treats the except-group parentheses as redundant and *strips* them, silently
  re-introducing 3.14-only syntax on every format; on `py312` ruff instead flags
  the bare form as `invalid-syntax`. Keeping dev tooling above the floor is a
  standing false-green generator, not a neutral choice.

## Checkpoints (one reviewable chunk per commit; nothing irreversible without explicit go-ahead)

1. **Licensing + packaging metadata.** Add `LICENSE` (MIT). Fill `pyproject`:
   `license`, `authors`, `readme`, `keywords`, `classifiers`, `[project.urls]`,
   reset `version = "0.0.1"`, relax `requires-python`. Configure the sdist target
   so internal `research/` and `reviews/` are excluded while `examples/` and
   `tests/` ship (decide deliberately, do not rely on defaults).
2. **README + CONTRIBUTING + CHANGELOG.** README: add a License section and repo
   links; it is otherwise already a full public landing page (install,
   quickstart, DSL reference, CLI, MCP, examples). `CONTRIBUTING.md`: uv dev
   setup, `uv run pytest`, ruff/ty, snapshot regen, the research/review-gated
   workflow, commit conventions. `CHANGELOG.md` (Keep a Changelog): a single
   `0.0.1` entry honestly summarizing the engine's current scope and its bounds
   (bounded reachability; no liveness/temporal; safety + reachability only).
3. **Build + clean-install validation.** `uv build`; inspect wheel + sdist
   contents (no research/reviews, src + entry points present); `twine check`;
   install the built wheel into a throwaway venv on **Python 3.12** and smoke-test
   `analint check examples/...`, `analint --help`, the `mcp` extra. Run the full
   suite under 3.12 to prove the relaxed floor.
4. **Publish (irreversible — only after explicit confirmation).** TestPyPI
   dry-run first, then PyPI. Confirm GitHub repo visibility (currently unknown —
   `gh` not authed); if private, making it public is a separate explicit step.
   Tag `v0.0.1` + GitHub release. A PyPI version cannot be re-uploaded once
   taken, so this checkpoint is held until the user says go.

## Deferred within this phase

- Full docs site (MkDocs/Material). The 726-line README covers the surface; a
  separate site is a follow-up, not a blocker for 0.0.1.
- CI publishing workflow (GitHub Actions → PyPI trusted publishing). Worth doing
  but can follow the first manual release.
