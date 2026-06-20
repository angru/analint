# ruff: noqa: E712  (DSL: `== True/False` builds a Predicate; see research/27)
"""GitHub protected-branch / required pull-request policy — an external,
change-oriented evidence model (ROADMAP evidence gate, research/20 §"first
external candidate").

This is a real system not invented for analint: GitHub's branch protection on a
required pull request. A PR may merge into a protected branch only when the
policy holds — enough approving reviews (one of them from a code owner), no
outstanding "changes requested" review, required status checks passing, and the
branch up to date with its base.

Modelled configuration (one explicit GitHub setting set, see research/23 for the
source/assumption matrix):

    required approving reviews  = 2   (a code-owner approval counts as one)
    require review from code owners = enabled
    dismiss stale approvals on push = enabled
    require branches up to date (strict checks) = enabled
    allow bypass = disabled

Key fidelity points the model gets right:

- A code-owner approval *is* an approving review: it counts toward the required
  total, so two reviews (one a code owner) suffice — not three.
- A new commit (``push_commit``) dismisses stale *approvals* but does NOT clear a
  blocking "changes requested" review — that must be explicitly dismissed /
  re-reviewed (``dismiss_changes_request``).
- ``update_branch`` creates a new head commit (merging base in), so it also
  dismisses stale approvals and re-runs checks. ``base_advanced`` only moves the
  base (head unchanged) and so leaves approvals alone — it just puts the PR
  behind.

The point of the exercise (compared with Quint / FizzBee) is to check whether a
*state-machine* model in a domain-readable DSL captures this faithfully and how
cheaply it survives requirement changes — see research/23 for the write-up.

The verification value is in the queries: across EVERY reachable action order,
a merge can never bypass the policy (the Unreachable guards), the policy is
achievable (Reachable), and a merged PR provably satisfied the policy (the
auto-verified invariant). The two executable Flows pin the two subtle journeys:
a blocking review must be explicitly resolved, and a push forces re-approval.
"""

from enum import StrEnum

from analint import (
    Action,
    AlwaysHolds,
    And,
    Assert,
    Entity,
    Expect,
    Field,
    Flow,
    Implies,
    Invariant,
    Lifecycle,
    Reachable,
    Scenario,
    Set,
    Spec,
    Transition,
    Unreachable,
)

REQUIRED_APPROVALS = 2


class PRState(StrEnum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class Checks(StrEnum):
    PENDING = "pending"
    PASSING = "passing"
    FAILING = "failing"


class PullRequest(Entity):
    state: PRState = Lifecycle(
        initial=PRState.OPEN,
        transitions=[Transition(PRState.OPEN, [PRState.MERGED, PRState.CLOSED])],
        terminal=[PRState.MERGED, PRState.CLOSED],  # a merged/closed PR is frozen
    )
    # Threshold-capped approving-review count. Saturation lets a code owner
    # approve after two ordinary reviewers without creating an artificial third
    # count state; the policy only cares whether the threshold was reached.
    approvals: int = Field(0, ge=0, le=REQUIRED_APPROVALS, saturate=True)
    code_owner_approved: bool = Field(False)  # at least one approval is a code owner's
    changes_requested: bool = Field(False)
    checks: Checks = Field(Checks.PENDING)
    behind_base: bool = Field(False)  # base branch advanced; PR is not up to date


# ── The branch-protection policy: when may a PR merge? ───────────────────────────
mergeable = And(
    PullRequest.approvals >= REQUIRED_APPROVALS,
    PullRequest.code_owner_approved == True,
    PullRequest.changes_requested == False,
    PullRequest.checks == Checks.PASSING,
    PullRequest.behind_base == False,
)
is_open = PullRequest.state == PRState.OPEN

# ── Review actions ───────────────────────────────────────────────────────────────
approve = Action(
    name="An ordinary reviewer approves the pull request",
    pre=[is_open, PullRequest.approvals < REQUIRED_APPROVALS],
    effect=[Set(PullRequest.approvals, PullRequest.approvals + 1)],
)

code_owner_approve = Action(
    name="A code owner approves (counts as an approving review)",
    pre=[
        is_open,
        PullRequest.code_owner_approved == False,
    ],
    effect=[
        Set(PullRequest.approvals, PullRequest.approvals + 1),
        Set(PullRequest.code_owner_approved, True),
    ],
)

request_changes = Action(
    name="A reviewer requests changes (blocks merge until dismissed)",
    pre=[is_open],
    effect=[Set(PullRequest.changes_requested, True)],
)

dismiss_changes_request = Action(
    name="The blocking 'changes requested' review is dismissed / re-reviewed",
    pre=[is_open, PullRequest.changes_requested == True],
    effect=[Set(PullRequest.changes_requested, False)],
)

# ── Commit / CI actions ──────────────────────────────────────────────────────────
push_commit = Action(
    name="A new commit is pushed: stale approvals dismissed, checks re-run",
    pre=[is_open],
    # A new commit dismisses stale *approvals* and re-runs checks. It does NOT
    # clear a blocking 'changes requested' review — that needs an explicit
    # dismissal / re-review (dismiss_changes_request).
    effect=[
        Set(PullRequest.approvals, 0),
        Set(PullRequest.code_owner_approved, False),
        Set(PullRequest.checks, Checks.PENDING),
    ],
)

checks_pass = Action(
    name="Required status checks pass",
    pre=[is_open, PullRequest.checks == Checks.PENDING],
    effect=[Set(PullRequest.checks, Checks.PASSING)],
)

checks_fail = Action(
    name="Required status checks fail",
    pre=[is_open, PullRequest.checks == Checks.PENDING],
    effect=[Set(PullRequest.checks, Checks.FAILING)],
)

# ── Base-branch actions ──────────────────────────────────────────────────────────
base_advanced = Action(
    name="The base branch advances; the PR is now behind (head unchanged)",
    pre=[is_open, PullRequest.behind_base == False],
    effect=[Set(PullRequest.behind_base, True)],
)

update_branch = Action(
    name="Update the branch from base: a new head commit, so approvals are dismissed",
    pre=[is_open, PullRequest.behind_base == True],
    # Updating merges base into the head — a new commit — so stale approvals are
    # dismissed and checks must re-run, just like push_commit.
    effect=[
        Set(PullRequest.behind_base, False),
        Set(PullRequest.approvals, 0),
        Set(PullRequest.code_owner_approved, False),
        Set(PullRequest.checks, Checks.PENDING),
    ],
)

# ── Terminal actions ─────────────────────────────────────────────────────────────
merge = Action(
    name="Merge the pull request (only when the policy holds)",
    pre=[is_open, mergeable],
    effect=[Set(PullRequest.state, PRState.MERGED)],
)

close = Action(
    name="Close the pull request without merging",
    pre=[is_open],
    effect=[Set(PullRequest.state, PRState.CLOSED)],
)


# ── Invariants ───────────────────────────────────────────────────────────────────
# A merged PR provably satisfied the policy.
merged_satisfied_policy = Invariant(
    Implies(PullRequest.state == PRState.MERGED, mergeable),
    label="a merged PR satisfied the branch-protection policy",
)

# Abstraction soundness: a code-owner approval is itself an approval, so the flag
# can never be set without at least one approval backing it.
code_owner_is_an_approval = Invariant(
    Implies(PullRequest.code_owner_approved == True, PullRequest.approvals >= 1),
    label="a code-owner approval counts as at least one approving review",
)


# ── Scenarios — concrete, hand-checked cases ─────────────────────────────────────
# Negative merge scenarios are single-fault: every other policy condition is
# satisfied and exactly one is broken, so each scenario can only stay PASS while
# its own target condition is actually enforced.
_ALL_GREEN = dict(
    approvals=2,
    code_owner_approved=True,
    checks=Checks.PASSING,
    behind_base=False,
    changes_requested=False,
)

sc_merge_happy = Scenario(
    name="A fully-approved, green, up-to-date PR merges",
    action=merge,
    given=[PullRequest(**_ALL_GREEN)],
    then=[PullRequest.state == PRState.MERGED],
)

sc_merge_underapproved = Scenario(
    name="Cannot merge with too few approvals (only the count differs)",
    action=merge,
    given=[PullRequest(**{**_ALL_GREEN, "approvals": 1})],
    expected=Expect.FAIL,
)

sc_merge_without_code_owner = Scenario(
    name="Cannot merge without a code-owner approval (only that differs)",
    action=merge,
    given=[PullRequest(**{**_ALL_GREEN, "code_owner_approved": False})],
    expected=Expect.FAIL,
)

sc_merge_failing_checks = Scenario(
    name="Cannot merge with failing checks (only checks differ)",
    action=merge,
    given=[PullRequest(**{**_ALL_GREEN, "checks": Checks.FAILING})],
    expected=Expect.FAIL,
)

sc_merge_behind_base = Scenario(
    name="Cannot merge while behind the base branch (only that differs)",
    action=merge,
    given=[PullRequest(**{**_ALL_GREEN, "behind_base": True})],
    expected=Expect.FAIL,
)

sc_merge_with_changes_requested = Scenario(
    name="Cannot merge with an outstanding changes-requested review (only that differs)",
    action=merge,
    given=[PullRequest(**{**_ALL_GREEN, "changes_requested": True})],
    expected=Expect.FAIL,
)

sc_push_dismisses_approvals = Scenario(
    name="A new commit dismisses stale approvals and re-runs checks",
    action=push_commit,
    given=[PullRequest(approvals=2, code_owner_approved=True, checks=Checks.PASSING)],
    then=[
        PullRequest.approvals == 0,
        PullRequest.code_owner_approved == False,
        PullRequest.checks == Checks.PENDING,
    ],
)

sc_push_keeps_changes_requested = Scenario(
    name="A new commit does NOT clear a blocking changes-requested review",
    action=push_commit,
    given=[PullRequest(changes_requested=True)],
    then=[PullRequest.changes_requested == True],
)

sc_approve = Scenario(
    name="An ordinary reviewer adds an approval",
    action=approve,
    given=[PullRequest(approvals=1, code_owner_approved=True)],
    then=[PullRequest.approvals == 2],
)

sc_code_owner_approve = Scenario(
    name="A code owner approves: counts as an approval and sets the flag",
    action=code_owner_approve,
    given=[PullRequest()],
    then=[
        PullRequest.approvals == 1,
        PullRequest.code_owner_approved == True,
    ],
)

sc_code_owner_can_approve_after_threshold = Scenario(
    name="A code owner can approve after the ordinary-review threshold is reached",
    action=code_owner_approve,
    given=[PullRequest(approvals=2)],
    then=[
        PullRequest.approvals == 2,
        PullRequest.code_owner_approved == True,
    ],
)

sc_request_changes = Scenario(
    name="A reviewer requests changes",
    action=request_changes,
    given=[PullRequest()],
    then=[PullRequest.changes_requested == True],
)

sc_dismiss_changes_request = Scenario(
    name="The blocking changes-requested review is dismissed",
    action=dismiss_changes_request,
    given=[PullRequest(changes_requested=True)],
    then=[PullRequest.changes_requested == False],
)

sc_checks_pass = Scenario(
    name="Pending checks pass",
    action=checks_pass,
    given=[PullRequest(checks=Checks.PENDING)],
    then=[PullRequest.checks == Checks.PASSING],
)

sc_checks_fail = Scenario(
    name="Pending checks fail",
    action=checks_fail,
    given=[PullRequest(checks=Checks.PENDING)],
    then=[PullRequest.checks == Checks.FAILING],
)

sc_base_advanced = Scenario(
    name="The base branch advances; the PR falls behind (approvals untouched)",
    action=base_advanced,
    given=[PullRequest(approvals=2, code_owner_approved=True)],
    then=[
        PullRequest.behind_base == True,
        PullRequest.approvals == 2,
    ],
)

sc_update_branch = Scenario(
    name="Updating from base is a new commit: clears 'behind', dismisses approvals",
    action=update_branch,
    given=[
        PullRequest(behind_base=True, approvals=2, code_owner_approved=True, checks=Checks.PASSING)
    ],
    then=[
        PullRequest.behind_base == False,
        PullRequest.approvals == 0,
        PullRequest.code_owner_approved == False,
        PullRequest.checks == Checks.PENDING,
    ],
)

sc_close = Scenario(
    name="A PR can be closed without merging",
    action=close,
    given=[PullRequest(**_ALL_GREEN)],
    then=[PullRequest.state == PRState.CLOSED],
)


# ── Flows — the two subtle journeys, run end to end ──────────────────────────────
# A blocking review is not cleared by a push: it must be explicitly dismissed
# before the (re-)approved, green PR can merge.
flow_changes_request_blocks_until_dismissed = Flow(
    given=[PullRequest()],
    steps=[
        request_changes,
        Assert(PullRequest.changes_requested == True),
        push_commit,  # a new commit does not clear the blocking review
        Assert(PullRequest.changes_requested == True),
        dismiss_changes_request,  # only an explicit dismissal clears it
        approve,
        code_owner_approve,
        checks_pass,
        merge,
        Assert(PullRequest.state == PRState.MERGED),
    ],
)

# A push after full approval dismisses the approvals: the PR must be approved
# again (including a fresh code-owner approval) before it can merge.
flow_push_forces_reapproval = Flow(
    given=[PullRequest()],
    steps=[
        approve,
        code_owner_approve,
        Assert(PullRequest.approvals == 2),
        push_commit,
        Assert(PullRequest.approvals == 0),
        Assert(PullRequest.code_owner_approved == False),
        approve,
        code_owner_approve,
        checks_pass,
        merge,
        Assert(PullRequest.state == PRState.MERGED),
    ],
)


# ── Queries — the policy holds across EVERY reachable action order ────────────────
merge_is_achievable = Reachable(
    PullRequest.state == PRState.MERGED,
    label="some sequence of reviews/checks/updates leads to a merge",
)

never_merge_underapproved = Unreachable(
    And(PullRequest.state == PRState.MERGED, PullRequest.approvals < REQUIRED_APPROVALS),
    label="a PR can never merge with too few approvals",
)

never_merge_without_code_owner = Unreachable(
    And(PullRequest.state == PRState.MERGED, PullRequest.code_owner_approved == False),
    label="a PR can never merge without a code-owner approval",
)

never_merge_failing = Unreachable(
    And(PullRequest.state == PRState.MERGED, PullRequest.checks == Checks.FAILING),
    label="a PR can never merge with failing checks",
)

never_merge_with_changes = Unreachable(
    And(PullRequest.state == PRState.MERGED, PullRequest.changes_requested == True),
    label="a PR can never merge with outstanding change requests",
)

never_merge_behind = Unreachable(
    And(PullRequest.state == PRState.MERGED, PullRequest.behind_base == True),
    label="a PR can never merge while behind its base branch",
)

policy_always_holds = AlwaysHolds(
    Implies(PullRequest.state == PRState.MERGED, mergeable),
    label="every reachable merged state satisfies the policy",
)


spec = Spec(
    id="branch_protection",
    name="GitHub protected-branch pull-request policy",
    version="1.0.0",
    description="A required PR into a protected branch: approvals (one from a code "
    "owner), stale-review dismissal, required checks, and up-to-date-with-base — "
    "verified to be unbypassable across every action order.",
)
