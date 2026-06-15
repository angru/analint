# branch_protection — GitHub protected-branch pull-request policy

## Purpose & source
A real, externally documented system: GitHub's branch protection on a required
pull request (RFC-style docs, not invented for analint). The first external
evidence model (research/23), with a source/assumption matrix tracing each
modelled rule back to the GitHub documentation.

## Modeled scope & omissions
One aggregated `PullRequest` with required approvals (one from a code owner),
stale-review dismissal on push, required status checks, and up-to-date-with-base.
Deliberately omitted: multiple PRs / merge queue, reviewer identities, CI bound to
a head SHA, admin bypass, asynchronous delivery. "Changes addressed" / "stale
review" are path/temporal facts; the guarantee here is structural (one clearer +
guard + Flow witness).

## Key entities / actions / properties
- `PullRequest` lifecycle `OPEN → MERGED|CLOSED`; fields: approvals, code_owner_approved,
  changes_requested, checks, behind_base.
- Actions: approve, code_owner_approve, request_changes, dismiss_changes_request,
  push_commit, checks_pass/fail, base_advanced, update_branch, merge, close.
- `merge_is_achievable` (Reachable), `never_merge_*` (Unreachable mutation detectors),
  `policy_always_holds` (AlwaysHolds), two soundness invariants. 121 reachable states.

## Run
```
uv run analint check examples/branch_protection
```

## Expected outcome
PASS, exit 0, no warnings. Each `never_merge_*` is a mutation detector: deleting its
conjunct from `mergeable` flips it to FAIL.

## What a behavioural change means
Relaxing the policy (e.g. dropping the up-to-date rule) makes the matching
`never_merge_*` reachable and turns its guard FAIL — the verifier names exactly
which guarantee was lost. See the measured four-change series in research/23.

## Related research
research/23 (evidence model + change series).
