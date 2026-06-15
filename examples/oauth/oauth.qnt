/**
 * Bounded OAuth 2.0 Authorization Code + PKCE model.
 *
 * This is the comparison port of the analint model in protocol.py and
 * assurance.py. Both models use two code slots, two token slots, two clients,
 * two redirect values, and two abstract PKCE verifier/challenge values.
 *
 * Run with Quint 0.32.0:
 *
 *   npx --yes @informalsystems/quint@0.32.0 typecheck examples/oauth/oauth.qnt
 *   npx --yes @informalsystems/quint@0.32.0 test examples/oauth/oauth.qnt \
 *     --main=oauth --match='test.*'
 *   npx --yes @informalsystems/quint@0.32.0 run examples/oauth/oauth.qnt \
 *     --main=oauth --invariant=allSafety --max-samples=10000 \
 *     --max-steps=20 --seed=0x5eed
 */
module oauth {
  type Code = {
    state: str,
    codeId: str,
    client: str,
    redirect: str,
    challenge: str,
  }

  type Token = {
    state: str,
    sourceCode: str,
    issuedTo: str,
    viaRedirect: str,
    viaVerifier: str,
  }

  pure val CODE_SLOTS = Set("c1", "c2")
  pure val TOKEN_SLOTS = Set("t1", "t2")
  pure val CLIENTS = Set("honest", "attacker")
  pure val REDIRECTS = Set("redirect-a", "redirect-b")
  pure val VERIFIERS = Set("verifier-1", "verifier-2")

  pure def codeId(slot: str): str =
    if (slot == "c1") "code-1" else "code-2"

  pure def emptyCode(slot: str): Code = {
    state: "unissued",
    codeId: codeId(slot),
    client: "honest",
    redirect: "redirect-a",
    challenge: "verifier-1",
  }

  pure def emptyToken: Token = {
    state: "absent",
    sourceCode: "code-1",
    issuedTo: "honest",
    viaRedirect: "redirect-a",
    viaVerifier: "verifier-1",
  }

  var codes: str -> Code
  var tokens: str -> Token

  action init = all {
    codes' = CODE_SLOTS.mapBy(slot => emptyCode(slot)),
    tokens' = TOKEN_SLOTS.mapBy(_ => emptyToken),
  }

  action issueCode(
    codeSlot: str,
    client: str,
    redirect: str,
    challenge: str
  ): bool = {
    val current = codes.get(codeSlot)
    all {
      current.state == "unissued",
      codes' = codes.set(codeSlot, {
        ...current,
        state: "issued",
        codeId: codeId(codeSlot),
        client: client,
        redirect: redirect,
        challenge: challenge,
      }),
      tokens' = tokens,
    }
  }

  action redeemCode(
    codeSlot: str,
    tokenSlot: str,
    asClient: str,
    presented: str,
    verifier: str
  ): bool = {
    val currentCode = codes.get(codeSlot)
    val currentToken = tokens.get(tokenSlot)
    all {
      currentCode.state == "issued",
      currentToken.state == "absent",
      asClient == currentCode.client,
      presented == currentCode.redirect,
      verifier == currentCode.challenge,
      codes' = codes.set(codeSlot, { ...currentCode, state: "redeemed" }),
      tokens' = tokens.set(tokenSlot, {
        ...currentToken,
        state: "active",
        sourceCode: currentCode.codeId,
        issuedTo: asClient,
        viaRedirect: presented,
        viaVerifier: verifier,
      }),
    }
  }

  action detectReplayAndRevoke(
    codeSlot: str,
    tokenSlot: str,
    asClient: str,
    presented: str,
    verifier: str
  ): bool = {
    val currentCode = codes.get(codeSlot)
    val currentToken = tokens.get(tokenSlot)
    all {
      currentCode.state == "redeemed",
      asClient == currentCode.client,
      presented == currentCode.redirect,
      verifier == currentCode.challenge,
      currentToken.state == "active",
      currentToken.sourceCode == currentCode.codeId,
      codes' = codes.set(codeSlot, { ...currentCode, state: "replay-detected" }),
      tokens' = tokens.set(tokenSlot, { ...currentToken, state: "revoked" }),
    }
  }

  action step = {
    nondet codeSlot = CODE_SLOTS.oneOf()
    nondet tokenSlot = TOKEN_SLOTS.oneOf()
    nondet client = CLIENTS.oneOf()
    nondet redirect = REDIRECTS.oneOf()
    nondet verifier = VERIFIERS.oneOf()
    any {
      issueCode(codeSlot, client, redirect, verifier),
      redeemCode(codeSlot, tokenSlot, client, redirect, verifier),
      detectReplayAndRevoke(codeSlot, tokenSlot, client, redirect, verifier),
      // Stutter: idle in terminal/quiescent states. analint treats terminal
      // states as normal endpoints of its BFS; Apalache's `verify` reports a
      // state with no enabled action as a deadlock. Stuttering preserves every
      // safety invariant and removes no real transition, so it makes the
      // bounded safety check well-defined without weakening it.
      all { codes' = codes, tokens' = tokens },
    }
  }

  val everyTokenTracesToItsCode =
    TOKEN_SLOTS.forall(tokenSlot => {
      val token = tokens.get(tokenSlot)
      token.state != "absent" implies
        CODE_SLOTS.exists(codeSlot => {
          val code = codes.get(codeSlot)
          and {
            Set("redeemed", "replay-detected").contains(code.state),
            token.sourceCode == code.codeId,
            token.issuedTo == code.client,
          }
        })
    })

  val noTokenToWrongClient =
    not(TOKEN_SLOTS.exists(tokenSlot =>
      CODE_SLOTS.exists(codeSlot => {
        val token = tokens.get(tokenSlot)
        val code = codes.get(codeSlot)
        and {
          token.state == "active",
          code.state == "redeemed",
          token.sourceCode == code.codeId,
          token.issuedTo != code.client,
        }
      })
    ))

  val noTokenViaMismatchedRedirect =
    not(TOKEN_SLOTS.exists(tokenSlot =>
      CODE_SLOTS.exists(codeSlot => {
        val token = tokens.get(tokenSlot)
        val code = codes.get(codeSlot)
        and {
          token.state == "active",
          code.state == "redeemed",
          token.sourceCode == code.codeId,
          token.viaRedirect != code.redirect,
        }
      })
    ))

  val noTokenWithWrongVerifier =
    not(TOKEN_SLOTS.exists(tokenSlot =>
      CODE_SLOTS.exists(codeSlot => {
        val token = tokens.get(tokenSlot)
        val code = codes.get(codeSlot)
        and {
          token.state == "active",
          code.state == "redeemed",
          token.sourceCode == code.codeId,
          token.viaVerifier != code.challenge,
        }
      })
    ))

  val onlyReplayedCodesTokensAreRevoked =
    not(TOKEN_SLOTS.exists(tokenSlot =>
      CODE_SLOTS.exists(codeSlot => {
        val token = tokens.get(tokenSlot)
        val code = codes.get(codeSlot)
        and {
          token.state == "revoked",
          code.state == "redeemed",
          token.sourceCode == code.codeId,
        }
      })
    ))

  val replayDetectedCodeHasNoActiveToken =
    not(TOKEN_SLOTS.exists(tokenSlot =>
      CODE_SLOTS.exists(codeSlot => {
        val token = tokens.get(tokenSlot)
        val code = codes.get(codeSlot)
        and {
          code.state == "replay-detected",
          token.sourceCode == code.codeId,
          token.state == "active",
        }
      })
    ))

  val allSafety = and {
    everyTokenTracesToItsCode,
    noTokenToWrongClient,
    noTokenViaMismatchedRedirect,
    noTokenWithWrongVerifier,
    onlyReplayedCodesTokensAreRevoked,
    replayDetectedCodeHasNoActiveToken,
  }

  run testHonestFlow = {
    init
      .then(issueCode("c1", "honest", "redirect-a", "verifier-1"))
      .then(redeemCode("c1", "t1", "honest", "redirect-a", "verifier-1"))
      .then(all {
        assert(tokens.get("t1").state == "active"),
        assert(tokens.get("t1").issuedTo == "honest"),
        codes' = codes,
        tokens' = tokens,
      })
  }

  run testWrongClientIsBlocked = {
    init
      .then(issueCode("c1", "honest", "redirect-a", "verifier-1"))
      .then(redeemCode("c1", "t1", "attacker", "redirect-a", "verifier-1"))
      .fail()
  }

  run testWrongVerifierIsBlocked = {
    init
      .then(issueCode("c1", "honest", "redirect-a", "verifier-1"))
      .then(redeemCode("c1", "t1", "honest", "redirect-a", "verifier-2"))
      .fail()
  }

  run testReplayRevokesDerivedToken = {
    init
      .then(issueCode("c1", "honest", "redirect-a", "verifier-1"))
      .then(redeemCode("c1", "t1", "honest", "redirect-a", "verifier-1"))
      .then(detectReplayAndRevoke("c1", "t1", "honest", "redirect-a", "verifier-1"))
      .then(all {
        assert(codes.get("c1").state == "replay-detected"),
        assert(tokens.get("t1").state == "revoked"),
        codes' = codes,
        tokens' = tokens,
      })
  }

  run testUnrelatedTokenIsNotRevoked = {
    init
      .then(issueCode("c1", "honest", "redirect-a", "verifier-1"))
      .then(issueCode("c2", "honest", "redirect-a", "verifier-1"))
      .then(redeemCode("c2", "t1", "honest", "redirect-a", "verifier-1"))
      .then(detectReplayAndRevoke("c1", "t1", "honest", "redirect-a", "verifier-1"))
      .fail()
  }
}
