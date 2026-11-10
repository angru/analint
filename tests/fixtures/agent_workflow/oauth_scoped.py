from oauth.protocol import TokenState, codes, tokens

from analint import And, Bound, Count, ForAll, Invariant, Key, Reachable

wf_code = Bound("wf_code", codes)
wf_token = Bound("wf_token", tokens)
one_active_token_per_code = Invariant(
    ForAll(
        wf_code,
        Count(
            wf_token, And(wf_token.state == TokenState.ACTIVE, wf_token.source_code == Key(wf_code))
        )
        <= 1,
    )
)
independent_codes_can_issue = Reachable(Count(wf_token, wf_token.state == TokenState.ACTIVE) == 2)
