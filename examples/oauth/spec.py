"""OAuth 2.0 Authorization Code Grant + PKCE external evidence model.

The protocol and its assurance suite are separate explicit contracts. This is
whole-fragment composition, not the cross-cutting behavioral refinement that
PKCE was shown to require in research/24.

Environmental assumptions: resource-owner consent, HTTP/TLS/browser behavior,
entropy, SHA-256, expiration, and distributed duplicate issuance are outside
the bounded model. PKCE matching uses finite verifier/challenge identities.
"""

from analint import Spec

from .assurance import assurance_contract
from .protocol import protocol_contract

spec = Spec(
    id="oauth",
    name="OAuth 2.0 authorization-code grant + PKCE (RFC 6749 §4.1, RFC 7636)",
    version="0.6.0",
    description="Two clients, two code slots and two token slots with client, "
    "redirect and PKCE binding plus replay-triggered revocation. The root composes "
    "a protocol contract and an independently exported assurance contract.",
    imports=[protocol_contract, assurance_contract],
)
