"""Bounded OAuth Authorization Code + PKCE protocol surface.

This module owns the state and transition relation. It deliberately exports a
closed ``Contract`` so the assurance suite can be maintained separately without
depending on loader discovery.
"""

from enum import StrEnum

from analint import (
    Action,
    Contract,
    Entity,
    Field,
    Implies,
    Lifecycle,
    Param,
    Scope,
    Set,
    Transition,
)


class CodeState(StrEnum):
    UNISSUED = "unissued"
    ISSUED = "issued"
    REDEEMED = "redeemed"
    REPLAY_DETECTED = "replay_detected"


class TokenState(StrEnum):
    ABSENT = "absent"
    ACTIVE = "active"
    REVOKED = "revoked"


class Client(StrEnum):
    HONEST = "honest"
    ATTACKER = "attacker"


class Redirect(StrEnum):
    A = "https://app-a.example/cb"
    B = "https://app-b.example/cb"


class Pkce(StrEnum):
    V1 = "verifier-1"
    V2 = "verifier-2"


class CodeId(StrEnum):
    C1 = "code-1"
    C2 = "code-2"


class AuthCode(Entity):
    state: CodeState = Lifecycle(
        initial=CodeState.UNISSUED,
        transitions=[
            Transition(CodeState.UNISSUED, [CodeState.ISSUED]),
            Transition(CodeState.ISSUED, [CodeState.REDEEMED]),
            Transition(CodeState.REDEEMED, [CodeState.REPLAY_DETECTED]),
        ],
        terminal=[CodeState.REPLAY_DETECTED],
    )
    code_id: CodeId = Field(CodeId.C1)
    client: Client = Field(Client.HONEST)
    redirect: Redirect = Field(Redirect.A)
    challenge: Pkce = Field(Pkce.V1)


class Token(Entity):
    state: TokenState = Lifecycle(
        initial=TokenState.ABSENT,
        transitions=[
            Transition(TokenState.ABSENT, [TokenState.ACTIVE]),
            Transition(TokenState.ACTIVE, [TokenState.REVOKED]),
        ],
        terminal=[TokenState.REVOKED],
    )
    source_code: CodeId = Field(CodeId.C1)
    issued_to: Client = Field(Client.HONEST)
    via_redirect: Redirect = Field(Redirect.A)
    via_verifier: Pkce = Field(Pkce.V1)


codes = Scope(AuthCode, keys=["c1", "c2"])
tokens = Scope(Token, keys=["t1", "t2"])

code = Param("code", codes)
token = Param("token", tokens)
code_id = Param("code_id", CodeId.C1, CodeId.C2)
client = Param("client", Client.HONEST, Client.ATTACKER)
as_client = Param("as_client", Client.HONEST, Client.ATTACKER)
redirect = Param("redirect", Redirect.A, Redirect.B)
challenge = Param("challenge", Pkce.V1, Pkce.V2)
presented = Param("presented", Redirect.A, Redirect.B)
verifier = Param("verifier", Pkce.V1, Pkce.V2)

# The model needs a value-level identity for provenance. Scope identity is not
# directly storable in a field, so this relation pins each slot to its CodeId.
_slot_is_its_id = [
    Implies(code == codes["c1"], code_id == CodeId.C1),
    Implies(code == codes["c2"], code_id == CodeId.C2),
]

issue_code = Action(
    id="issue_code",
    name="The authorization server issues a code, bound to client, redirect, PKCE",
    params=[code, code_id, client, redirect, challenge],
    where=_slot_is_its_id,
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
    id="redeem_code",
    name="A client redeems a code, presenting client, redirect URI and PKCE verifier",
    params=[code, code_id, token, as_client, presented, verifier],
    where=_slot_is_its_id,
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

detect_replay_and_revoke = Action(
    id="detect_replay_and_revoke",
    name="A replayed code is detected: deny re-use and revoke its derived token",
    params=[code, code_id, token, as_client, presented, verifier],
    where=_slot_is_its_id,
    pre=[
        code.state == CodeState.REDEEMED,
        as_client == code.client,
        presented == code.redirect,
        verifier == code.challenge,
        token.state == TokenState.ACTIVE,
        token.source_code == code_id,
    ],
    effect=[
        Set(code.state, CodeState.REPLAY_DETECTED),
        Set(token.state, TokenState.REVOKED),
    ],
)


protocol_contract = Contract(
    id="oauth-protocol",
    name="OAuth authorization-code protocol",
    version="0.5.0",
    description="Bounded RFC 6749 authorization-code flow with PKCE and replay revocation.",
    entities=[AuthCode, Token],
    scopes=[codes, tokens],
    actions=[issue_code, redeem_code, detect_replay_and_revoke],
)
