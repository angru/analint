# oauth — OAuth 2.0 Authorization Code + PKCE

## Purpose & source
The second external evidence model (research/24): OAuth 2.0 Authorization Code Grant
with PKCE — RFC 6749 §4.1/§4.1.3/§10.5 and RFC 7636. Chosen because its key
guarantees are *safety* (an attacker never gets a token they should not), which a
reachability engine can verify honestly.

## Modeled scope & omissions
Two clients (honest + attacker), two authorization-code slots and two token slots,
two redirect URIs and two abstract PKCE verifier/challenge identities. Issuance,
redemption (client + redirect + PKCE all must match), and replay detection with
derived-token revocation. Omitted (abstracted into actions): consent UI, HTTP/TLS,
entropy, the SHA-256 transform (modelled as identity equality), and expiration.

## Structure (explicit composition)
Three-file package: `protocol.py` (entities/scopes/actions), `assurance.py`
(scenarios/flows/properties), and `spec.py` (root importing both contracts). The
split is no-semantic-change — see the Contract finding in research/24.

## Key properties
`honest_flow_reaches_token` (Reachable), `every_token_traces_to_its_code`
(AlwaysHolds, relational provenance), and `no_token_to_wrong_client /
_via_mismatched_redirect / _with_wrong_verifier` plus replay properties
(Unreachable). 1169 reachable states, 2256 edges.

## Run
```
uv run analint check examples/oauth
```
Quint comparison port (`oauth.qnt`), needs Quint 0.32.0 (and Java 17 for `verify`):
```
quint test examples/oauth/oauth.qnt --main=oauth --match='test.*'
quint verify examples/oauth/oauth.qnt --main=oauth --invariant=allSafety --max-steps=12
```

## Expected outcome
PASS, exit 0, no warnings.

## What a behavioural change means
Dropping a redemption guard makes the matching `no_token_*` reachable (and its
isolated attacker scenario stops being blocked) — see the five-step change series
and the Quint cross-check in research/24.

## Related research
research/24 (selection, change series, Quint comparison), research/25 (synthesis).
