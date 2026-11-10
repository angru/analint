from analint_spec import Checks, PRState, PullRequest, merge

from analint import And, Reachable, Scenario

requested_merge_behind = Scenario(
    action=merge,
    given=[
        PullRequest(approvals=2, code_owner_approved=True, checks=Checks.PASSING, behind_base=True)
    ],
    then=[PullRequest.state == PRState.MERGED],
)
requested_loose_merge = Reachable(And(PullRequest.state == PRState.MERGED, PullRequest.behind_base))
