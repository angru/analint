"""OAuth 2.0 Authorization Code Grant (RFC 6749 §4.1) — the second external
evidence model (research/24). A real, RFC-documented protocol, deliberately
chosen because its important guarantees are *safety* (an attacker can never
obtain a token they should not) rather than liveness — so a green verdict from a
reachability engine is honest evidence, not a silently weakened contract.

This file is **step 1 of the change series**: the single-client authorization-
code core. An authorization code is issued after the resource owner approves,
then exchanged exactly once for an access token. Later steps (see research/24)
add exact redirect-URI binding, PKCE as a separate Contract, a second client with
an intercepted-code attacker, and replay detection — those are where the
composition + identity pressure lands.

Verified here (single instances, so the claims are modest by design):

- the honest flow can obtain a token (Reachable);
- a token exists only after its code was redeemed (Unreachable / Invariant);
- the executable Flow pins approve → issue → redeem → token.

Single-use *across interleavings*, cross-client redemption and PKCE are not yet
expressible with one code and one token slot — they arrive with multiplicity in
the later steps, by design. The source/assumption matrix lives in research/24;
this model does not claim to verify HTTP, TLS, entropy, hashing, or expiration.
"""

from enum import StrEnum

from analint import (
    Action,
    And,
    Assert,
    Entity,
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


class CodeState(StrEnum):
    UNISSUED = "unissued"  # no code issued yet for this authorization
    ISSUED = "issued"  # a single-use authorization code is outstanding
    REDEEMED = "redeemed"  # the code has been exchanged for a token (spent)


class TokenState(StrEnum):
    ABSENT = "absent"
    ACTIVE = "active"


class AuthCode(Entity):
    state: CodeState = Lifecycle(
        initial=CodeState.UNISSUED,
        transitions=[
            Transition(CodeState.UNISSUED, [CodeState.ISSUED]),
            Transition(CodeState.ISSUED, [CodeState.REDEEMED]),
        ],
        terminal=[CodeState.REDEEMED],  # a spent code is frozen — single-use
    )


class Token(Entity):
    state: TokenState = Lifecycle(
        initial=TokenState.ABSENT,
        transitions=[Transition(TokenState.ABSENT, [TokenState.ACTIVE])],
        terminal=[TokenState.ACTIVE],
    )


# ── Actions — RFC 6749 §4.1 happy path ───────────────────────────────────────────
issue_code = Action(
    name="The authorization server issues a code after the owner approves",
    pre=[AuthCode.state == CodeState.UNISSUED],
    effect=[Set(AuthCode.state, CodeState.ISSUED)],
)

redeem_code = Action(
    name="The client exchanges the authorization code for an access token",
    pre=[AuthCode.state == CodeState.ISSUED, Token.state == TokenState.ABSENT],
    effect=[
        Set(AuthCode.state, CodeState.REDEEMED),
        Set(Token.state, TokenState.ACTIVE),
    ],
)


# ── Invariant — abstraction soundness ────────────────────────────────────────────
token_implies_redeemed = Invariant(
    Implies(Token.state == TokenState.ACTIVE, AuthCode.state == CodeState.REDEEMED),
    label="an active token exists only after its code was redeemed",
)


# ── Scenarios ────────────────────────────────────────────────────────────────────
sc_issue = Scenario(
    name="A code is issued after approval",
    action=issue_code,
    given=[AuthCode()],
    then=[Assert(AuthCode.state == CodeState.ISSUED)],
)

sc_redeem = Scenario(
    name="An issued code is exchanged for a token",
    action=redeem_code,
    given=[AuthCode(state=CodeState.ISSUED), Token()],
    then=[
        Assert(Token.state == TokenState.ACTIVE),
        Assert(AuthCode.state == CodeState.REDEEMED),
    ],
)


# ── Flow — the executable happy path ─────────────────────────────────────────────
flow_happy_path = Flow(
    given=[AuthCode(), Token()],
    steps=[
        issue_code,
        Assert(AuthCode.state == CodeState.ISSUED),
        redeem_code,
        Assert(Token.state == TokenState.ACTIVE),
        Assert(AuthCode.state == CodeState.REDEEMED),
    ],
)


# ── Queries — properties across every reachable order ────────────────────────────
honest_flow_reaches_token = Reachable(
    Token.state == TokenState.ACTIVE,
    label="the honest authorization-code flow can obtain an access token",
)

no_token_without_redeemed_code = Unreachable(
    And(Token.state == TokenState.ACTIVE, AuthCode.state != CodeState.REDEEMED),
    label="a token can never exist without a redeemed authorization code",
)


spec = Spec(
    id="oauth",
    name="OAuth 2.0 authorization-code grant (RFC 6749 §4.1)",
    version="0.1.0",
    description="Step 1: the single-client authorization-code core — a code is "
    "issued, then exchanged exactly once for an access token. Redirect binding, "
    "PKCE and the cross-client attacker arrive in later steps (research/24).",
)
