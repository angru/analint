"""OAuth 2.0 Authorization Code Grant + PKCE — the second external evidence model
(research/24). A real, RFC-documented protocol, deliberately chosen because its
important guarantees are *safety* (an attacker can never obtain a token they
should not) rather than liveness — so a green verdict from a reachability engine
is honest evidence, not a silently weakened contract.

What is modelled (bounded for exhaustive BFS):

- RFC 6749 §4.1 authorization-code core: a code is issued, then exchanged exactly
  once for an access token (single-use — a spent code is terminal).
- RFC 6749 §4.1.3 exact redirect-URI binding and client binding: redemption only
  succeeds when the presented redirect URI and redeeming client match the code.
- RFC 7636 PKCE: the code is bound to a `code_challenge` at issuance and the
  matching `code_verifier` must be presented at redemption.
- **Multiplicity (step 4):** two authorization-code slots and two token slots,
  two client identities (an honest client and an attacker). This is the real
  composition + relational-identity experiment — the interception attack that
  redirect binding and PKCE exist to defeat.

Verified across every reachable action order:

- the honest flow can obtain a token (Reachable);
- every active token has provenance: it came from a redeemed code issued to that
  same client, with the redirect/verifier it presented (AlwaysHolds, relational);
- a token is never issued to a client other than the code's owner, via a
  mismatched redirect, or with a wrong PKCE verifier (Unreachable).

Attacker tests are isolated single-fault mutation detectors (one guard each), not
a realistic "fails everything" attempt:

- ``sc_attacker_wrong_client``: correct redirect + verifier, wrong client →
  isolates the client binding;
- ``sc_attacker_wrong_verifier``: impersonates the honest client, wrong verifier
  → isolates PKCE.

Environmental assumptions (NOT modelled — abstracted into the actions): the
resource-owner consent UI (``issue_code`` stands for "the server issued a code
after the owner approved"); HTTP, TLS, browsers; entropy; the SHA-256 transform
(PKCE matching is modelled as equality of finite verifier/challenge identities);
and code/token expiration. The source/assumption matrix lives in research/24.

Architectural finding — PKCE is NOT a separate Contract (negative evidence).
``Contract`` (src/analint/models/contract.py) is a closed union of whole
behavioural fragments with identity deduplication — no entity-schema extension
and no way to add a guard/effect to an existing action. PKCE *refines* an
existing entity (`challenge` on ``AuthCode``) and transition (a verifier guard on
``redeem_code``), so it cannot be an additive contract: a parallel PKCE
redemption would leave the original ``redeem_code`` as a PKCE bypass, and closing
that means modifying/excluding the core action — no longer additive composition.
Conclusion: whole-fragment composition works; cross-cutting behavioural
refinement is unsupported, and one case does not justify adding it. PKCE is
therefore integrated; the failed expectation is the evidence (research/24).

Still to come (research/24): replay detection / token revocation, and the closing
Quint or FizzBee port.
"""

from enum import StrEnum

from analint import (
    Action,
    AlwaysHolds,
    And,
    Assert,
    Bound,
    Entity,
    Exists,
    Expect,
    Field,
    Flow,
    ForAll,
    Implies,
    Lifecycle,
    Param,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Transition,
    Unreachable,
)


class CodeState(StrEnum):
    UNISSUED = "unissued"  # no code issued yet for this slot
    ISSUED = "issued"  # a single-use authorization code is outstanding
    REDEEMED = "redeemed"  # the code has been exchanged for a token (spent)


class TokenState(StrEnum):
    ABSENT = "absent"
    ACTIVE = "active"


class Client(StrEnum):
    HONEST = "honest"  # the legitimate client
    ATTACKER = "attacker"  # a client that may intercept codes


# Registered redirect URIs (RFC 6749 §4.1.3 binds redemption to the redirect URI).
class Redirect(StrEnum):
    A = "https://app-a.example/cb"
    B = "https://app-b.example/cb"


# PKCE verifier/challenge identities (RFC 7636). The SHA-256 transform is
# abstracted: a verifier "matches" a challenge iff they are the same identity.
class Pkce(StrEnum):
    V1 = "verifier-1"
    V2 = "verifier-2"


# Stable identity of an authorization-code slot — lets a token point back to the
# code it came from (provenance), needed for the relational property and later
# for revocation (step 5).
class CodeId(StrEnum):
    C1 = "code-1"
    C2 = "code-2"


class AuthCode(Entity):
    state: CodeState = Lifecycle(
        initial=CodeState.UNISSUED,
        transitions=[
            Transition(CodeState.UNISSUED, [CodeState.ISSUED]),
            Transition(CodeState.ISSUED, [CodeState.REDEEMED]),
        ],
        terminal=[CodeState.REDEEMED],  # a spent code is frozen — single-use
    )
    code_id: CodeId = Field(CodeId.C1)  # this slot's stable identity (set at issue)
    client: Client = Field(Client.HONEST)  # the client the code was issued to
    redirect: Redirect = Field(Redirect.A)  # the redirect URI the code is bound to
    challenge: Pkce = Field(Pkce.V1)  # PKCE code_challenge bound at issuance


class Token(Entity):
    state: TokenState = Lifecycle(
        initial=TokenState.ABSENT,
        transitions=[Transition(TokenState.ABSENT, [TokenState.ACTIVE])],
        terminal=[TokenState.ACTIVE],
    )
    source_code: CodeId = Field(CodeId.C1)  # the code this token was minted from
    issued_to: Client = Field(Client.HONEST)  # the client that received the token
    via_redirect: Redirect = Field(Redirect.A)  # redirect presented at redemption
    via_verifier: Pkce = Field(Pkce.V1)  # PKCE verifier presented at redemption


codes = Scope(AuthCode, keys=["c1", "c2"])
tokens = Scope(Token, keys=["t1", "t2"])

# Bounds for the relational properties; Params for the parameterized actions.
code_q = Bound("code", codes)
token_q = Bound("token", tokens)


# ── Actions — RFC 6749 §4.1 + RFC 7636 over a bounded universe ────────────────────
code = Param("code", codes)
token = Param("token", tokens)
code_id = Param("code_id", CodeId.C1, CodeId.C2)
client = Param("client", Client.HONEST, Client.ATTACKER)
as_client = Param("as_client", Client.HONEST, Client.ATTACKER)
redirect = Param("redirect", Redirect.A, Redirect.B)
challenge = Param("challenge", Pkce.V1, Pkce.V2)
presented = Param("presented", Redirect.A, Redirect.B)
verifier = Param("verifier", Pkce.V1, Pkce.V2)

# Statically tie each code slot to its stable CodeId, so issuance can stamp it.
_slot_is_its_id = [
    Implies(code == codes["c1"], code_id == CodeId.C1),
    Implies(code == codes["c2"], code_id == CodeId.C2),
]

issue_code = Action(
    name="The authorization server issues a code, bound to client, redirect, PKCE",
    params=[code, code_id, client, redirect, challenge],
    where=_slot_is_its_id,
    # Abstracts "the server issued a code after the resource owner approved".
    pre=[code.state == CodeState.UNISSUED],
    effect=[
        Set(code.state, CodeState.ISSUED),
        Set(code.code_id, code_id),
        Set(code.client, client),
        Set(code.redirect, redirect),
        Set(code.challenge, challenge),
    ],
)

redeem_code = Action(
    name="A client redeems a code, presenting client, redirect URI and PKCE verifier",
    params=[code, code_id, token, as_client, presented, verifier],
    where=_slot_is_its_id,
    # RFC 6749 §4.1.3 + RFC 7636 §4.6 — redemption only succeeds when the
    # redeeming client, presented redirect URI and PKCE verifier all match the
    # code's bindings. The token records its provenance.
    pre=[
        code.state == CodeState.ISSUED,
        token.state == TokenState.ABSENT,
        as_client == code.client,
        presented == code.redirect,
        verifier == code.challenge,
    ],
    effect=[
        Set(code.state, CodeState.REDEEMED),
        Set(token.state, TokenState.ACTIVE),
        Set(token.source_code, code_id),
        Set(token.issued_to, as_client),
        Set(token.via_redirect, presented),
        Set(token.via_verifier, verifier),
    ],
)


# ── Scenarios ────────────────────────────────────────────────────────────────────
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


# ── Flow — the executable happy path ─────────────────────────────────────────────
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


# ── Queries — properties across every reachable action order ──────────────────────
honest_flow_reaches_token = Reachable(
    Exists(token_q, token_q.state == TokenState.ACTIVE),
    label="the honest authorization-code flow can obtain an access token",
)

# Relational provenance: every active token came from a redeemed code that was
# issued to that same client. This ties tokens to codes by identity, not by
# coincidence of fields.
every_token_traces_to_its_code = AlwaysHolds(
    ForAll(
        token_q,
        Implies(
            token_q.state == TokenState.ACTIVE,
            Exists(
                code_q,
                And(
                    code_q.state == CodeState.REDEEMED,
                    token_q.source_code == code_q.code_id,
                    token_q.issued_to == code_q.client,
                ),
            ),
        ),
    ),
    label="every active token came from a redeemed code issued to that same client",
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


spec = Spec(
    id="oauth",
    name="OAuth 2.0 authorization-code grant + PKCE (RFC 6749 §4.1, RFC 7636)",
    version="0.4.0",
    description="Two clients (honest + attacker), two code slots and two token "
    "slots: a code is issued bound to client/redirect/PKCE and redeemed exactly "
    "once only when all three match. The interception attack redirect binding and "
    "PKCE exist to defeat. Replay detection / revocation arrives next (research/24).",
)
