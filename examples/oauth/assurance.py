"""Reusable assurance suite for the bounded OAuth protocol contract."""

from analint import (
    AlwaysHolds,
    And,
    Assert,
    Bound,
    Contract,
    Exists,
    Expect,
    Flow,
    ForAll,
    Implies,
    In,
    Reachable,
    Scenario,
    Unreachable,
)

from .protocol import (
    Client,
    CodeId,
    CodeState,
    Pkce,
    Redirect,
    TokenState,
    codes,
    detect_replay_and_revoke,
    issue_code,
    redeem_code,
    tokens,
)

code_q = Bound("code", codes)
token_q = Bound("token", tokens)


sc_issue = Scenario(
    name="A code is issued, bound to client, redirect URI and PKCE challenge",
    action=issue_code.bind(
        code=codes["c1"],
        code_id=CodeId.C1,
        client=Client.HONEST,
        redirect=Redirect.A,
        challenge=Pkce.V1,
    ),
    given=[codes["c1"](), codes["c2"](), tokens["t1"](), tokens["t2"]()],
    then=[
        Assert(codes["c1"].state == CodeState.ISSUED),
        Assert(codes["c1"].client == Client.HONEST),
    ],
)

sc_redeem = Scenario(
    name="A code is exchanged for a token with matching client, redirect and verifier",
    action=redeem_code.bind(
        code=codes["c1"],
        code_id=CodeId.C1,
        token=tokens["t1"],
        as_client=Client.HONEST,
        presented=Redirect.A,
        verifier=Pkce.V1,
    ),
    given=[
        codes["c1"](
            state=CodeState.ISSUED,
            code_id=CodeId.C1,
            client=Client.HONEST,
            redirect=Redirect.A,
            challenge=Pkce.V1,
        ),
        codes["c2"](),
        tokens["t1"](),
        tokens["t2"](),
    ],
    then=[
        Assert(tokens["t1"].state == TokenState.ACTIVE),
        Assert(tokens["t1"].issued_to == Client.HONEST),
        Assert(codes["c1"].state == CodeState.REDEEMED),
    ],
)

sc_attacker_wrong_client = Scenario(
    name="Attacker with the correct redirect and verifier but wrong client is blocked",
    action=redeem_code.bind(
        code=codes["c1"],
        code_id=CodeId.C1,
        token=tokens["t1"],
        as_client=Client.ATTACKER,
        presented=Redirect.A,
        verifier=Pkce.V1,
    ),
    given=[
        codes["c1"](
            state=CodeState.ISSUED,
            code_id=CodeId.C1,
            client=Client.HONEST,
            redirect=Redirect.A,
            challenge=Pkce.V1,
        ),
        codes["c2"](),
        tokens["t1"](),
        tokens["t2"](),
    ],
    expected=Expect.FAIL,
)

sc_attacker_wrong_verifier = Scenario(
    name="Attacker impersonating the honest client but with a wrong verifier is blocked",
    action=redeem_code.bind(
        code=codes["c1"],
        code_id=CodeId.C1,
        token=tokens["t1"],
        as_client=Client.HONEST,
        presented=Redirect.A,
        verifier=Pkce.V2,
    ),
    given=[
        codes["c1"](
            state=CodeState.ISSUED,
            code_id=CodeId.C1,
            client=Client.HONEST,
            redirect=Redirect.A,
            challenge=Pkce.V1,
        ),
        codes["c2"](),
        tokens["t1"](),
        tokens["t2"](),
    ],
    expected=Expect.FAIL,
)

sc_replay_revokes_derived_token = Scenario(
    name="Replaying a redeemed code is detected and revokes its derived token",
    action=detect_replay_and_revoke.bind(
        code=codes["c1"],
        code_id=CodeId.C1,
        token=tokens["t1"],
        as_client=Client.HONEST,
        presented=Redirect.A,
        verifier=Pkce.V1,
    ),
    given=[
        codes["c1"](
            state=CodeState.REDEEMED,
            code_id=CodeId.C1,
            client=Client.HONEST,
            redirect=Redirect.A,
            challenge=Pkce.V1,
        ),
        codes["c2"](),
        tokens["t1"](state=TokenState.ACTIVE, source_code=CodeId.C1, issued_to=Client.HONEST),
        tokens["t2"](),
    ],
    then=[
        Assert(codes["c1"].state == CodeState.REPLAY_DETECTED),
        Assert(tokens["t1"].state == TokenState.REVOKED),
    ],
)

sc_revoke_unrelated_token_blocked = Scenario(
    name="Replay detection cannot revoke a token that did not come from this code",
    action=detect_replay_and_revoke.bind(
        code=codes["c1"],
        code_id=CodeId.C1,
        token=tokens["t1"],
        as_client=Client.HONEST,
        presented=Redirect.A,
        verifier=Pkce.V1,
    ),
    given=[
        codes["c1"](
            state=CodeState.REDEEMED,
            code_id=CodeId.C1,
            client=Client.HONEST,
            redirect=Redirect.A,
            challenge=Pkce.V1,
        ),
        codes["c2"](),
        tokens["t1"](state=TokenState.ACTIVE, source_code=CodeId.C2, issued_to=Client.HONEST),
        tokens["t2"](),
    ],
    expected=Expect.FAIL,
)


flow_happy_path = Flow(
    given=[codes["c1"](), codes["c2"](), tokens["t1"](), tokens["t2"]()],
    steps=[
        issue_code.bind(
            code=codes["c1"],
            code_id=CodeId.C1,
            client=Client.HONEST,
            redirect=Redirect.A,
            challenge=Pkce.V1,
        ),
        Assert(codes["c1"].state == CodeState.ISSUED),
        redeem_code.bind(
            code=codes["c1"],
            code_id=CodeId.C1,
            token=tokens["t1"],
            as_client=Client.HONEST,
            presented=Redirect.A,
            verifier=Pkce.V1,
        ),
        Assert(tokens["t1"].state == TokenState.ACTIVE),
        Assert(codes["c1"].state == CodeState.REDEEMED),
    ],
)

flow_replay_revokes = Flow(
    given=[codes["c1"](), codes["c2"](), tokens["t1"](), tokens["t2"]()],
    steps=[
        issue_code.bind(
            code=codes["c1"],
            code_id=CodeId.C1,
            client=Client.HONEST,
            redirect=Redirect.A,
            challenge=Pkce.V1,
        ),
        redeem_code.bind(
            code=codes["c1"],
            code_id=CodeId.C1,
            token=tokens["t1"],
            as_client=Client.HONEST,
            presented=Redirect.A,
            verifier=Pkce.V1,
        ),
        Assert(tokens["t1"].state == TokenState.ACTIVE),
        detect_replay_and_revoke.bind(
            code=codes["c1"],
            code_id=CodeId.C1,
            token=tokens["t1"],
            as_client=Client.HONEST,
            presented=Redirect.A,
            verifier=Pkce.V1,
        ),
        Assert(codes["c1"].state == CodeState.REPLAY_DETECTED),
        Assert(tokens["t1"].state == TokenState.REVOKED),
    ],
)


honest_flow_reaches_token = Reachable(
    Exists(
        token_q,
        And(token_q.state == TokenState.ACTIVE, token_q.issued_to == Client.HONEST),
    ),
    label="the honest client can obtain an access token",
)

every_token_traces_to_its_code = AlwaysHolds(
    ForAll(
        token_q,
        Implies(
            token_q.state != TokenState.ABSENT,
            Exists(
                code_q,
                And(
                    In(code_q.state, [CodeState.REDEEMED, CodeState.REPLAY_DETECTED]),
                    token_q.source_code == code_q.code_id,
                    token_q.issued_to == code_q.client,
                ),
            ),
        ),
    ),
    label="every token (active or revoked) came from a spent code issued to that client",
)

no_token_to_wrong_client = Unreachable(
    Exists(
        token_q,
        Exists(
            code_q,
            And(
                token_q.state == TokenState.ACTIVE,
                code_q.state == CodeState.REDEEMED,
                token_q.source_code == code_q.code_id,
                token_q.issued_to != code_q.client,
            ),
        ),
    ),
    label="a token is never issued to a client other than its code's owner",
)

no_token_via_mismatched_redirect = Unreachable(
    Exists(
        token_q,
        Exists(
            code_q,
            And(
                token_q.state == TokenState.ACTIVE,
                code_q.state == CodeState.REDEEMED,
                token_q.source_code == code_q.code_id,
                token_q.via_redirect != code_q.redirect,
            ),
        ),
    ),
    label="a token is never issued via a redirect URI other than the code's binding",
)

no_token_with_wrong_verifier = Unreachable(
    Exists(
        token_q,
        Exists(
            code_q,
            And(
                token_q.state == TokenState.ACTIVE,
                code_q.state == CodeState.REDEEMED,
                token_q.source_code == code_q.code_id,
                token_q.via_verifier != code_q.challenge,
            ),
        ),
    ),
    label="a token is never issued without the PKCE verifier matching the challenge",
)

replay_can_reach_revocation = Reachable(
    Exists(token_q, token_q.state == TokenState.REVOKED),
    label="a replayed code can be detected and its derived token revoked",
)

only_replayed_codes_tokens_are_revoked = Unreachable(
    Exists(
        token_q,
        Exists(
            code_q,
            And(
                token_q.state == TokenState.REVOKED,
                code_q.state == CodeState.REDEEMED,
                token_q.source_code == code_q.code_id,
            ),
        ),
    ),
    label="a token is only revoked when its source code's replay was detected",
)

replay_detected_code_has_no_active_token = Unreachable(
    Exists(
        token_q,
        Exists(
            code_q,
            And(
                code_q.state == CodeState.REPLAY_DETECTED,
                token_q.source_code == code_q.code_id,
                token_q.state == TokenState.ACTIVE,
            ),
        ),
    ),
    label="a code whose replay was detected has no still-active derived token",
)


assurance_contract = Contract(
    id="oauth-assurance",
    name="OAuth protocol assurance suite",
    version="0.5.0",
    description="Executable examples and reachability properties over oauth-protocol.",
    flows=[flow_happy_path, flow_replay_revokes],
    scenarios=[
        sc_issue,
        sc_redeem,
        sc_attacker_wrong_client,
        sc_attacker_wrong_verifier,
        sc_replay_revokes_derived_token,
        sc_revoke_unrelated_token_blocked,
    ],
    queries=[
        honest_flow_reaches_token,
        every_token_traces_to_its_code,
        no_token_to_wrong_client,
        no_token_via_mismatched_redirect,
        no_token_with_wrong_verifier,
        replay_can_reach_revocation,
        only_replayed_codes_tokens_are_revoked,
        replay_detected_code_has_no_active_token,
    ],
)
