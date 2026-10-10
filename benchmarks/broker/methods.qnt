/**
 * Quint port of the broker M6 payment-method increment
 * (benchmarks/broker/methods.py with the client's security-code actions, entry
 * m6_methods.py) for the research/34 §8 B2 cross-check. It extends
 * examples/broker/broker.qnt.
 *
 * The analint kernel's implicit rules written out:
 *  - presence: the two method slots are records with `present`; an absent slot
 *    holds canonical (default) values, as analint's state key ignores absent
 *    fields; Create needs an absent slot, every other action a present one;
 *  - Count, Sum and ForAll range over present slots only;
 *  - Capacity (2 methods) is a constant: no action changes it;
 *  - every action that changes the client requires an active client;
 *  - Param bindings are chosen inside each action (see risk.qnt's lesson);
 *  - a safety-preserving stutter keeps quiescent states from being deadlocks.
 *
 *   quint typecheck benchmarks/broker/methods.qnt
 *   quint test benchmarks/broker/methods.qnt --main=methods
 *   quint verify benchmarks/broker/methods.qnt --main=methods --backend=tlc \
 *     --init=initMethodsOnly --step=stepMethodsOnly --invariant=methodInvariants
 */
module methods {
  import broker.* from "../../examples/broker/broker"

  type MKind = MkCard | MkBank
  type Currency = CuUnit | CuOther
  type MSlot = MsCard | MsBank
  type Method = {
    present: bool,
    kind: MKind,
    currency: Currency,
    ownName: bool,
    eligible: bool,
    held: int,
    requested: bool,
  }
  type Ledger = { currency: Currency, funded: int, balance: int, paid: int }

  pure val SLOTS = Set(MsCard, MsBank)
  pure val METHOD_CAPACITY = 2
  pure val NO_METHOD: Method = {
    present: false,
    kind: MkCard,
    currency: CuUnit,
    ownName: true,
    eligible: false,
    held: 0,
    requested: false,
  }
  pure val NEW_LEDGER: Ledger = { currency: CuUnit, funded: 0, balance: 0, paid: 0 }

  var slots: MSlot -> Method
  var ledger: Ledger

  action initMethodsOnly = {
    nondet region = Set(RStandard, RDepositsGated, RTradingGated).oneOf()
    all {
      client' = { ...newClient(region), onboarding: ODetails, tier: TLow },
      acct' = ABSENT,
      slots' = SLOTS.mapBy(_ => NO_METHOD),
      ledger' = NEW_LEDGER,
    }
  }

  action methodsUnchanged = all { slots' = slots, ledger' = ledger }

  val presentSlots = SLOTS.filter(s => slots.get(s).present)

  action registerMethod(slot: MSlot, kind: MKind, currency: Currency, ownName: bool): bool = all {
    client.status == CActive,
    presentSlots.size() < METHOD_CAPACITY,
    not(slots.get(slot).present),
    slots' = slots.set(slot, { ...NO_METHOD, present: true, kind: kind, currency: currency, ownName: ownName }),
    ledger' = ledger, client' = client, acct' = acct,
  }

  action fundByMethod(slot: MSlot): bool = {
    val m = slots.get(slot)
    all {
      client.status == CActive,
      m.present,
      m.ownName,
      m.currency == ledger.currency,
      ledger.funded < 2,
      client.tier != TNone,
      client.region == RDepositsGated implies client.tier == TFull,
      ledger' = { ...ledger, funded: ledger.funded + 1, balance: ledger.balance + 1 },
      slots' = slots.set(slot, { ...m, eligible: true }),
      client' = client, acct' = acct,
    }
  }

  action requestMethodPayout(slot: MSlot): bool = {
    val m = slots.get(slot)
    all {
      client.status == CActive,
      m.present,
      client.codeConfirmed,
      m.ownName,
      m.eligible,
      m.currency == ledger.currency,
      not(m.requested),
      ledger.balance >= 1,
      ledger' = { ...ledger, balance: ledger.balance - 1 },
      slots' = slots.set(slot, { ...m, held: 1, requested: true }),
      client' = { ...client, codeConfirmed: false },
      acct' = acct,
    }
  }

  action settleMethodPayout(slot: MSlot): bool = {
    val m = slots.get(slot)
    all {
      m.present,
      m.requested,
      slots' = slots.set(slot, { ...m, held: 0, requested: false }),
      ledger' = { ...ledger, paid: ledger.paid + 1 },
      client' = client, acct' = acct,
    }
  }

  action rejectMethodPayout(slot: MSlot): bool = {
    val m = slots.get(slot)
    all {
      m.present,
      m.requested,
      slots' = slots.set(slot, { ...m, held: 0, requested: false }),
      ledger' = { ...ledger, balance: ledger.balance + 1 },
      client' = client, acct' = acct,
    }
  }

  action methodActions = any {
    {
      nondet slot = SLOTS.oneOf()
      nondet kind = Set(MkCard, MkBank).oneOf()
      nondet currency = Set(CuUnit, CuOther).oneOf()
      nondet ownName = Set(false, true).oneOf()
      registerMethod(slot, kind, currency, ownName)
    },
    { nondet slot = SLOTS.oneOf() fundByMethod(slot) },
    { nondet slot = SLOTS.oneOf() requestMethodPayout(slot) },
    { nondet slot = SLOTS.oneOf() settleMethodPayout(slot) },
    { nondet slot = SLOTS.oneOf() rejectMethodPayout(slot) },
  }

  action stepMethodsOnly = any {
    methodActions,
    all { requestCode, methodsUnchanged },
    all { codeExpires, methodsUnchanged },
    all { client' = client, acct' = acct, methodsUnchanged },
  }

  val heldTotal = presentSlots.fold(0, (sum, s) => sum + slots.get(s).held)
  val methodMoneyIsConserved = ledger.funded == ledger.balance + ledger.paid + heldTotal
  val methodRequestMatchesHold = presentSlots.forall(s => {
    val m = slots.get(s)
    (not(m.requested) implies m.held == 0) and (m.requested implies m.held == 1)
  })
  val methodCapacityIsRespected = presentSlots.size() <= METHOD_CAPACITY
  val methodInvariants = and {
    methodMoneyIsConserved, methodRequestMatchesHold, methodCapacityIsRespected,
  }
  // Reachable(two methods hold payouts): a violation is the witness
  val notTwoPayoutsHeld = presentSlots.filter(s => slots.get(s).requested).size() < 2

  // ── scenarios (a representative subset of the analint ones) ─────────────

  pure val verified = {
    ...newClient(RStandard),
    onboarding: OProfile,
    identityDoc: DApproved,
    addressDoc: DApproved,
    tier: TFull,
    codeConfirmed: true,
  }
  pure val card = { ...NO_METHOD, present: true }

  action givenMethods(c: Client, cardSlot: Method, l: Ledger): bool = all {
    client' = c, acct' = ABSENT, slots' = Map(MsCard -> cardSlot, MsBank -> NO_METHOD), ledger' = l,
  }

  run thirdPartyFundingIsRejectedTest =
    givenMethods(verified, { ...card, ownName: false }, NEW_LEDGER).then(fundByMethod(MsCard)).fail()

  run wrongCurrencyFundingIsRejectedTest =
    givenMethods(verified, { ...card, currency: CuOther }, NEW_LEDGER).then(fundByMethod(MsCard)).fail()

  run methodFundingMakesPayoutEligibleTest =
    givenMethods(verified, card, NEW_LEDGER)
      .then(fundByMethod(MsCard))
      .expect(slots.get(MsCard).eligible and ledger.balance == 1)

  run methodPayoutConsumesCodeTest =
    givenMethods(verified, { ...card, eligible: true }, { ...NEW_LEDGER, funded: 1, balance: 1 })
      .then(requestMethodPayout(MsCard))
      .expect(slots.get(MsCard).held == 1 and ledger.balance == 0 and not(client.codeConfirmed))

  run methodPayoutWithoutCodeIsRejectedTest =
    givenMethods(
      { ...verified, codeConfirmed: false },
      { ...card, eligible: true },
      { ...NEW_LEDGER, funded: 1, balance: 1 },
    ).then(requestMethodPayout(MsCard)).fail()

  run rejectionRefundsHeldFundsTest =
    givenMethods(
      verified,
      { ...card, eligible: true, held: 1, requested: true },
      { ...NEW_LEDGER, funded: 1 },
    )
      .then(rejectMethodPayout(MsCard))
      .expect(ledger.balance == 1 and slots.get(MsCard).held == 0)
}
