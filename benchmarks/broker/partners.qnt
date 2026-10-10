/**
 * Quint port of the broker M5 partner increment (benchmarks/broker/partners.py
 * with the client's security-code actions, entry m5_partners.py) for the
 * research/34 §8 B2 cross-check. It extends examples/broker/broker.qnt.
 *
 * The analint kernel's implicit rules written out:
 *  - Partner's terminal lock (BLOCKED freezes it): every action that changes
 *    the partner already requires a non-blocked partner in its guard; the
 *    reward wallet is a separate entity, so accrued funds stay withdrawable;
 *  - every action that changes the client requires an active client;
 *  - Param bindings (status, qualification, amount) are chosen inside each
 *    action, so TLC enumerates only the successors that action can produce;
 *  - a safety-preserving stutter keeps quiescent states from being deadlocks.
 *
 *   quint typecheck benchmarks/broker/partners.qnt
 *   quint test benchmarks/broker/partners.qnt --main=partners
 *   quint verify benchmarks/broker/partners.qnt --main=partners --backend=tlc \
 *     --init=initPartnersOnly --step=stepPartnersOnly --invariant=rewardsAreConserved
 */
module partners {
  import broker.* from "../../examples/broker/broker"

  type PStatus = PsActive | PsLinkBlocked | PsOnHold | PsBlocked
  type PLevel = PlBase | PlAdvanced
  type Partner = { status: PStatus, level: PLevel, meetsRequirements: bool }
  type Wallet = { earned: int, accrued: int, paid: int }

  pure val STATUSES = Set(PsActive, PsLinkBlocked, PsOnHold, PsBlocked)
  pure val NEW_PARTNER: Partner = { status: PsActive, level: PlBase, meetsRequirements: false }
  pure val EMPTY_WALLET: Wallet = { earned: 0, accrued: 0, paid: 0 }

  var partner: Partner
  var attributed: bool
  var wallet: Wallet

  action initPartnersOnly = {
    nondet region = Set(RStandard, RDepositsGated, RTradingGated).oneOf()
    all {
      client' = { ...newClient(region), onboarding: OContacts },
      acct' = ABSENT,
      partner' = NEW_PARTNER,
      attributed' = false,
      wallet' = EMPTY_WALLET,
    }
  }

  action partnersUnchanged = all { partner' = partner, attributed' = attributed, wallet' = wallet }

  // the capability matrix: who may gain attribution, who may earn rewards
  val canAttribute = partner.status == PsActive or partner.status == PsOnHold
  val canReward = partner.status == PsActive or partner.status == PsLinkBlocked

  action changePartnerStatus(status: PStatus): bool = all {
    client.status == CActive,
    client.codeConfirmed,
    partner.status != PsBlocked,
    partner.status != status,
    partner' = { ...partner, status: status },
    client' = { ...client, codeConfirmed: false },
    acct' = acct,
    attributed' = attributed,
    wallet' = wallet,
  }

  action setPartnerQualification(qualified: bool): bool = all {
    partner.status != PsBlocked,
    partner.meetsRequirements != qualified,
    partner' = { ...partner, meetsRequirements: qualified },
    client' = client, acct' = acct, attributed' = attributed, wallet' = wallet,
  }

  action promotePartner = all {
    partner.status == PsActive,
    partner.meetsRequirements,
    partner.level == PlBase,
    partner' = { ...partner, level: PlAdvanced },
    client' = client, acct' = acct, attributed' = attributed, wallet' = wallet,
  }

  action automaticallyDowngradePartner = all {
    partner.status != PsBlocked,
    not(partner.meetsRequirements),
    partner.level == PlAdvanced,
    partner' = { ...partner, level: PlBase },
    client' = client, acct' = acct, attributed' = attributed, wallet' = wallet,
  }

  action attributeReferral = all {
    canAttribute,
    not(attributed),
    attributed' = true,
    client' = client, acct' = acct, partner' = partner, wallet' = wallet,
  }

  action accrueCommission(amount: int): bool = all {
    canReward,
    attributed,
    wallet.earned == 0,
    (partner.level == PlBase and amount == 1) or (partner.level == PlAdvanced and amount == 2),
    wallet' = { ...wallet, earned: wallet.earned + amount, accrued: wallet.accrued + amount },
    client' = client, acct' = acct, partner' = partner, attributed' = attributed,
  }

  action withdrawAccruedRewards = all {
    client.status == CActive,
    client.codeConfirmed,
    partner.status != PsOnHold,
    wallet.accrued > 0,
    wallet' = { ...wallet, paid: wallet.paid + wallet.accrued, accrued: 0 },
    client' = { ...client, codeConfirmed: false },
    acct' = acct,
    partner' = partner,
    attributed' = attributed,
  }

  action partnerActions = any {
    { nondet status = STATUSES.oneOf() changePartnerStatus(status) },
    { nondet qualified = Set(false, true).oneOf() setPartnerQualification(qualified) },
    promotePartner,
    automaticallyDowngradePartner,
    attributeReferral,
    { nondet amount = Set(1, 2).oneOf() accrueCommission(amount) },
    withdrawAccruedRewards,
  }

  action stepPartnersOnly = any {
    partnerActions,
    all { requestCode, partnersUnchanged },
    all { codeExpires, partnersUnchanged },
    all { client' = client, acct' = acct, partnersUnchanged },
  }

  val rewardsAreConserved = wallet.earned == wallet.accrued + wallet.paid
  // Reachable(blocked partner withdrew accrued rewards): a violation is the witness
  val notBlockedPartnerWithdrew = not(partner.status == PsBlocked and wallet.paid > 0)

  // ── scenarios (a representative subset of the analint ones) ─────────────

  action givenPartners(c: Client, p: Partner, a: bool, w: Wallet): bool = all {
    client' = c, acct' = ABSENT, partner' = p, attributed' = a, wallet' = w,
  }

  pure val coded = { ...newClient(RStandard), codeConfirmed: true }

  run partnerChangeSpendsCodeTest =
    givenPartners(coded, NEW_PARTNER, false, EMPTY_WALLET)
      .then(changePartnerStatus(PsLinkBlocked))
      .expect(partner.status == PsLinkBlocked and not(client.codeConfirmed))

  run partnerChangeWithoutCodeIsRejectedTest =
    givenPartners(newClient(RStandard), NEW_PARTNER, false, EMPTY_WALLET)
      .then(changePartnerStatus(PsOnHold))
      .fail()

  run blockedPartnerCannotReactivateTest =
    givenPartners(coded, { ...NEW_PARTNER, status: PsBlocked }, false, EMPTY_WALLET)
      .then(changePartnerStatus(PsActive))
      .fail()

  run linkBlockedPartnerCannotAttributeTest =
    givenPartners(newClient(RStandard), { ...NEW_PARTNER, status: PsLinkBlocked }, false, EMPTY_WALLET)
      .then(attributeReferral)
      .fail()

  run onHoldPartnerCannotEarnTest =
    givenPartners(newClient(RStandard), { ...NEW_PARTNER, status: PsOnHold }, true, EMPTY_WALLET)
      .then(accrueCommission(1))
      .fail()

  run blockedPartnerWithdrawsAccruedFundsTest =
    givenPartners(
      coded,
      { ...NEW_PARTNER, status: PsBlocked },
      true,
      { earned: 2, accrued: 2, paid: 0 },
    )
      .then(withdrawAccruedRewards)
      .expect(wallet.paid == 2 and wallet.accrued == 0 and not(client.codeConfirmed))

  run onHoldPartnerCannotWithdrawTest =
    givenPartners(coded, { ...NEW_PARTNER, status: PsOnHold }, true, { earned: 1, accrued: 1, paid: 0 })
      .then(withdrawAccruedRewards)
      .fail()
}
