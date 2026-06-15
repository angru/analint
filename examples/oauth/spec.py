"""OAuth 2.0 Authorization Code Grant + PKCE — the second external evidence model
(research/24). A real, RFC-documented protocol, deliberately chosen because its
important guarantees are *safety* (an attacker can never obtain a token they
should not) rather than liveness — so a green verdict from a reachability engine
is honest evidence, not a silently weakened contract.

What is modelled (single client, bounded for exhaustive BFS):

- RFC 6749 §4.1 authorization-code core: a code is issued, then exchanged exactly
  once for an access token (single-use — a spent code is terminal).
- RFC 6749 §4.1.3 exact redirect-URI binding: redemption only succeeds when the
  presented redirect URI matches the one the code was issued for.
- RFC 7636 PKCE: the code is bound to a `code_challenge` at issuance and the
  matching `code_verifier` must be presented at redemption.

Verified across every reachable action order:

- the honest flow can obtain a token (Reachable);
- a token exists only after its code was redeemed (Unreachable + Invariant);
- a token is never issued via a mismatched redirect URI (Unreachable);
- a token is never issued with a wrong PKCE verifier (Unreachable).

Environmental assumptions (NOT modelled — abstracted into the actions): the
resource-owner consent UI (``issue_code`` stands for "the server issued a code
after the owner approved"); HTTP, TLS, browsers; entropy; the SHA-256 transform
(PKCE matching is modelled as equality of finite verifier/challenge identities);
and code/token expiration. The source/assumption matrix lives in research/24.

Architectural finding — PKCE is NOT a separate Contract (negative evidence).
research/24 planned PKCE as its own ``Contract``. That was rejected: ``Contract``
(src/analint/models/contract.py) is a closed *union of whole behavioural
fragments* with identity deduplication — it has no entity-schema extension and no
way to add a guard/effect to an existing action. PKCE *refines* an existing
entity (a `challenge` field on ``AuthCode``) and an existing transition (a
verifier guard on ``redeem_code``), so it cannot be added as an additive
contract: a parallel PKCE redemption action would leave the original
``redeem_code`` as a PKCE bypass, and removing that bypass means modifying/
excluding the core action — no longer additive composition. The precise
conclusion: whole-fragment composition works; cross-cutting behavioural
refinement is unsupported, and one case is not enough to justify adding it.
PKCE is therefore integrated below; the failed expectation is the evidence.

Still to come (research/24): a second client with an intercepted-code attacker
(real composition + identity), replay detection / token revocation, and the
closing Quint or FizzBee port.
"""

from enum import StrEnum

from analint import (
    Action,
    And,
    Assert,
    Entity,
    Expect,
    Field,
    Flow,
    Implies,
    Invariant,
    Lifecycle,
    Param,
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


# Registered redirect URIs — finite identity values (RFC 6749 §4.1.3 binds
# redemption to the redirect URI the code was issued for).
class Redirect(StrEnum):
    A = "https://app-a.example/cb"
    B = "https://app-b.example/cb"


# PKCE verifier/challenge identities (RFC 7636). The SHA-256 transform is
# abstracted: a verifier "matches" a challenge iff they are the same identity.
class Pkce(StrEnum):
    V1 = "verifier-1"
    V2 = "verifier-2"


class AuthCode(Entity):
    state: CodeState = Lifecycle(
        initial=CodeState.UNISSUED,
        transitions=[
            Transition(CodeState.UNISSUED, [CodeState.ISSUED]),
            Transition(CodeState.ISSUED, [CodeState.REDEEMED]),
        ],
        terminal=[CodeState.REDEEMED],  # a spent code is frozen — single-use
    )
    redirect: Redirect = Field(Redirect.A)  # the redirect URI the code is bound to
    challenge: Pkce = Field(Pkce.V1)  # PKCE code_challenge bound at issuance


class Token(Entity):
    state: TokenState = Lifecycle(
        initial=TokenState.ABSENT,
        transitions=[Transition(TokenState.ABSENT, [TokenState.ACTIVE])],
        terminal=[TokenState.ACTIVE],
    )
    via_redirect: Redirect = Field(Redirect.A)  # redirect presented when redeemed
    via_verifier: Pkce = Field(Pkce.V1)  # PKCE verifier presented when redeemed


# ── Actions — RFC 6749 §4.1 + RFC 7636 ───────────────────────────────────────────
redirect = Param("redirect", Redirect.A, Redirect.B)
challenge = Param("challenge", Pkce.V1, Pkce.V2)
presented = Param("presented", Redirect.A, Redirect.B)
verifier = Param("verifier", Pkce.V1, Pkce.V2)

issue_code = Action(
    name="The authorization server issues a code bound to a redirect URI and PKCE challenge",
    params=[redirect, challenge],
    # Abstracts "the server issued a code after the resource owner approved".
    pre=[AuthCode.state == CodeState.UNISSUED],
    effect=[
        Set(AuthCode.state, CodeState.ISSUED),
        Set(AuthCode.redirect, redirect),
        Set(AuthCode.challenge, challenge),
    ],
)

redeem_code = Action(
    name="The client redeems the code with a matching redirect URI and PKCE verifier",
    params=[presented, verifier],
    # RFC 6749 §4.1.3 + RFC 7636 §4.6 — redemption only succeeds when the
    # presented redirect URI matches the code's binding AND the presented
    # verifier matches the code's challenge.
    pre=[
        AuthCode.state == CodeState.ISSUED,
        Token.state == TokenState.ABSENT,
        presented == AuthCode.redirect,
        verifier == AuthCode.challenge,
    ],
    effect=[
        Set(AuthCode.state, CodeState.REDEEMED),
        Set(Token.state, TokenState.ACTIVE),
        Set(Token.via_redirect, presented),
        Set(Token.via_verifier, verifier),
    ],
)


# ── Invariant — abstraction soundness ────────────────────────────────────────────
token_implies_redeemed = Invariant(
    Implies(Token.state == TokenState.ACTIVE, AuthCode.state == CodeState.REDEEMED),
    label="an active token exists only after its code was redeemed",
)


# ── Scenarios ────────────────────────────────────────────────────────────────────
sc_issue = Scenario(
    name="A code is issued, bound to its redirect URI and PKCE challenge",
    action=issue_code.bind(redirect=Redirect.A, challenge=Pkce.V1),
    given=[AuthCode()],
    then=[
        Assert(AuthCode.state == CodeState.ISSUED),
        Assert(AuthCode.redirect == Redirect.A),
        Assert(AuthCode.challenge == Pkce.V1),
    ],
)

sc_redeem = Scenario(
    name="An issued code is exchanged for a token with matching redirect and verifier",
    action=redeem_code.bind(presented=Redirect.A, verifier=Pkce.V1),
    given=[AuthCode(state=CodeState.ISSUED, redirect=Redirect.A, challenge=Pkce.V1), Token()],
    then=[
        Assert(Token.state == TokenState.ACTIVE),
        Assert(AuthCode.state == CodeState.REDEEMED),
    ],
)

sc_redeem_wrong_redirect = Scenario(
    name="Redemption with a non-matching redirect URI is rejected",
    action=redeem_code.bind(presented=Redirect.B, verifier=Pkce.V1),
    given=[AuthCode(state=CodeState.ISSUED, redirect=Redirect.A, challenge=Pkce.V1), Token()],
    expected=Expect.FAIL,
)

sc_redeem_wrong_verifier = Scenario(
    name="Redemption with a wrong PKCE verifier is rejected",
    action=redeem_code.bind(presented=Redirect.A, verifier=Pkce.V2),
    given=[AuthCode(state=CodeState.ISSUED, redirect=Redirect.A, challenge=Pkce.V1), Token()],
    expected=Expect.FAIL,
)


# ── Flow — the executable happy path ─────────────────────────────────────────────
flow_happy_path = Flow(
    given=[AuthCode(), Token()],
    steps=[
        issue_code.bind(redirect=Redirect.A, challenge=Pkce.V1),
        Assert(AuthCode.state == CodeState.ISSUED),
        redeem_code.bind(presented=Redirect.A, verifier=Pkce.V1),
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

no_token_via_mismatched_redirect = Unreachable(
    And(Token.state == TokenState.ACTIVE, Token.via_redirect != AuthCode.redirect),
    label="a token is never issued via a redirect URI other than the code's binding",
)

no_token_with_wrong_verifier = Unreachable(
    And(Token.state == TokenState.ACTIVE, Token.via_verifier != AuthCode.challenge),
    label="a token is never issued without the PKCE verifier matching the challenge",
)


spec = Spec(
    id="oauth",
    name="OAuth 2.0 authorization-code grant + PKCE (RFC 6749 §4.1, RFC 7636)",
    version="0.3.0",
    description="The single-client authorization-code core with exact redirect-URI "
    "binding and PKCE. A code is issued (bound to a redirect and a PKCE challenge) "
    "then exchanged exactly once for a token only when both match. The cross-client "
    "attacker and replay detection arrive in later steps (research/24).",
)
