/**
 * Quint port of examples/broker (increments M1–M3) — the research/34 §7
 * bake-off. Same abstraction and bounds as the analint model; the analint
 * kernel's implicit rules are written out explicitly here:
 *
 *  - terminal lock: every action that modifies the client requires an active
 *    client (Client.status TERMINATED freezes the whole entity in analint);
 *  - presence: the single account slot is a record with `present`; an absent
 *    slot holds canonical values (analint's state key ignores absent fields),
 *    so distinct-state counts are comparable;
 *  - a safety-preserving stutter keeps quiescent states from being reported as
 *    deadlocks (analint treats them as ordinary end states).
 *
 * The step is chosen per increment: --step=stepM1 | stepM2 | stepM3.
 *
 *   quint typecheck examples/broker/broker.qnt
 *   quint test examples/broker/broker.qnt --main=broker
 *   quint verify examples/broker/broker.qnt --main=broker --backend=tlc \
 *     --step=stepM3 --invariant=allInvariants
 *
 * TLC finds exactly analint's distinct-state counts: 132 / 1,770 / 15,912
 * for M1 / M2 / M3 (research/34 §8 D).
 */
module broker {
  type ClientStatus = CActive | CTerminated
  type Region = RStandard | RDepositsGated | RTradingGated
  type Onboarding = ONew | OContacts | ODetails | OProfile
  type Doc = DMissing | DPending | DRejected | DLocked | DApproved
  type Tier = TNone | TLow | THigher | TFull
  type Kind = KCent | KStandard | KProfessional
  type Mode = MReal | MDemo
  type AStatus = AActive | AArchived | ADisabled
  type Payout = PNone | PRequested

  type Client = {
    status: ClientStatus,
    region: Region,
    onboarding: Onboarding,
    identityDoc: Doc,
    identityFailures: int,
    addressDoc: Doc,
    addressFailures: int,
    tier: Tier,
    codeConfirmed: bool,
    cardOk: bool,
    deposited: int,
    withdrawn: int,
  }

  type Account = {
    present: bool,
    kind: Kind,
    mode: Mode,
    status: AStatus,
    balance: int,
    position: bool,
    payout: Payout,
  }

  pure val MONEY_CAP = 3
  pure val LAST_ATTEMPT = 1 // DOC_ATTEMPTS - 1

  pure def newClient(region: Region): Client = {
    status: CActive,
    region: region,
    onboarding: ONew,
    identityDoc: DMissing,
    identityFailures: 0,
    addressDoc: DMissing,
    addressFailures: 0,
    tier: TNone,
    codeConfirmed: false,
    cardOk: false,
    deposited: 0,
    withdrawn: 0,
  }

  pure val ABSENT: Account = {
    present: false,
    kind: KStandard,
    mode: MReal,
    status: AActive,
    balance: 0,
    position: false,
    payout: PNone,
  }

  var client: Client
  var acct: Account

  action init = {
    nondet region = Set(RStandard, RDepositsGated, RTradingGated).oneOf()
    all { client' = newClient(region), acct' = ABSENT }
  }

  // ── helpers ─────────────────────────────────────────────────────────────

  // an action that changes the client (the analint terminal lock)
  action updateClient(c: Client): bool = all {
    client.status == CActive,
    client' = c,
    acct' = acct,
  }

  action updateAccount(a: Account): bool = all {
    client' = client,
    acct' = a,
  }

  // ── M1: profile ─────────────────────────────────────────────────────────

  action confirmContacts = all {
    client.onboarding == ONew,
    updateClient({ ...client, onboarding: OContacts }),
  }

  action fillDetails = all {
    client.onboarding == OContacts,
    updateClient({ ...client, onboarding: ODetails, tier: TLow }),
  }

  action completeProfile = all {
    client.onboarding == ODetails,
    updateClient({ ...client, onboarding: OProfile }),
  }

  action submitIdentity = all {
    client.onboarding == OProfile,
    Set(DMissing, DRejected).contains(client.identityDoc),
    updateClient({ ...client, identityDoc: DPending }),
  }

  action approveIdentity = all {
    client.identityDoc == DPending,
    updateClient({ ...client, identityDoc: DApproved, tier: THigher }),
  }

  action rejectIdentity = all {
    client.identityDoc == DPending,
    client.identityFailures < LAST_ATTEMPT,
    updateClient({
      ...client,
      identityDoc: DRejected,
      identityFailures: client.identityFailures + 1,
    }),
  }

  action lockIdentity = all {
    client.identityDoc == DPending,
    client.identityFailures == LAST_ATTEMPT,
    updateClient({ ...client, identityDoc: DLocked }),
  }

  action supportReopensIdentity = all {
    client.identityDoc == DLocked,
    updateClient({ ...client, identityDoc: DMissing, identityFailures: 0 }),
  }

  action submitAddress = all {
    client.identityDoc == DApproved,
    Set(DMissing, DRejected).contains(client.addressDoc),
    updateClient({ ...client, addressDoc: DPending }),
  }

  action approveAddress = all {
    client.addressDoc == DPending,
    updateClient({ ...client, addressDoc: DApproved, tier: TFull }),
  }

  action rejectAddress = all {
    client.addressDoc == DPending,
    client.addressFailures < LAST_ATTEMPT,
    updateClient({
      ...client,
      addressDoc: DRejected,
      addressFailures: client.addressFailures + 1,
    }),
  }

  action lockAddress = all {
    client.addressDoc == DPending,
    client.addressFailures == LAST_ATTEMPT,
    updateClient({ ...client, addressDoc: DLocked }),
  }

  action supportReopensAddress = all {
    client.addressDoc == DLocked,
    updateClient({ ...client, addressDoc: DMissing, addressFailures: 0 }),
  }

  action requestCode = all {
    not(client.codeConfirmed),
    updateClient({ ...client, codeConfirmed: true }),
  }

  action codeExpires = all {
    client.codeConfirmed,
    updateClient({ ...client, codeConfirmed: false }),
  }

  // ── M2: trading accounts ────────────────────────────────────────────────

  action openAccount(kind: Kind, mode: Mode): bool = all {
    not(kind == KCent and mode == MDemo),
    client.status == CActive,
    client.onboarding != ONew,
    not(acct.present),
    updateAccount({ ...ABSENT, present: true, kind: kind, mode: mode }),
  }

  action archive = all {
    acct.present,
    acct.mode == MReal,
    acct.status == AActive,
    not(acct.position),
    acct.payout == PNone,
    updateAccount({ ...acct, status: AArchived }),
  }

  action restore = all {
    acct.present,
    client.status == CActive,
    acct.status == AArchived,
    updateAccount({ ...acct, status: AActive }),
  }

  action disable = all {
    acct.present,
    acct.mode == MReal,
    acct.status == AActive,
    updateAccount({ ...acct, status: ADisabled }),
  }

  action supportReactivates = all {
    acct.present,
    client.status == CActive,
    acct.status == ADisabled,
    updateAccount({ ...acct, status: AActive }),
  }

  action deleteInactiveDemo = all {
    acct.present,
    acct.mode == MDemo,
    acct.status == AActive,
    not(acct.position),
    updateAccount(ABSENT),
  }

  action openPosition = all {
    acct.present,
    client.status == CActive,
    acct.status == AActive,
    not(acct.position),
    acct.mode == MDemo or acct.balance >= 1,
    (client.region == RTradingGated and acct.mode == MReal) implies client.tier == TFull,
    updateAccount({ ...acct, position: true }),
  }

  action closePosition = all {
    acct.present,
    client.status == CActive,
    acct.status == AActive,
    acct.position,
    updateAccount({ ...acct, position: false }),
  }

  // ── M3: payments ────────────────────────────────────────────────────────

  val withinTierLimit = or {
    client.tier == TLow and client.deposited < 1,
    client.tier == THigher and client.deposited < 2,
    client.tier == TFull and client.deposited < MONEY_CAP,
  }

  action deposit = all {
    acct.present,
    client.status == CActive,
    acct.mode == MReal,
    acct.status == AActive,
    withinTierLimit,
    client.region == RDepositsGated implies client.tier == TFull,
    client' = { ...client, deposited: client.deposited + 1, cardOk: true },
    acct' = { ...acct, balance: acct.balance + 1 },
  }

  action verifyCard = all {
    not(client.cardOk),
    updateClient({ ...client, cardOk: true }),
  }

  action requestWithdrawal = all {
    acct.present,
    client.status == CActive,
    client.codeConfirmed,
    client.cardOk,
    acct.mode == MReal,
    acct.status == AActive,
    acct.payout == PNone,
    acct.balance >= 1,
    acct.position implies acct.balance >= 2,
    client' = { ...client, codeConfirmed: false },
    acct' = { ...acct, balance: acct.balance - 1, payout: PRequested },
  }

  action payWithdrawal = all {
    acct.present,
    acct.payout == PRequested,
    client.status == CActive,
    client' = { ...client, withdrawn: client.withdrawn + 1 },
    acct' = { ...acct, payout: PNone },
  }

  action rejectWithdrawal = all {
    acct.present,
    acct.payout == PRequested,
    updateAccount({ ...acct, payout: PNone, balance: acct.balance + 1 }),
  }

  action terminate = all {
    not(acct.present) or (acct.balance == 0 and acct.payout == PNone and not(acct.position)),
    updateClient({ ...client, status: CTerminated }),
  }

  // ── steps per increment ─────────────────────────────────────────────────

  action stutter = all { client' = client, acct' = acct }

  action profileActions = any {
    confirmContacts, fillDetails, completeProfile,
    submitIdentity, approveIdentity, rejectIdentity, lockIdentity, supportReopensIdentity,
    submitAddress, approveAddress, rejectAddress, lockAddress, supportReopensAddress,
    requestCode, codeExpires,
  }

  action openAnyAccount = {
    nondet kind = Set(KCent, KStandard, KProfessional).oneOf()
    nondet mode = Set(MReal, MDemo).oneOf()
    openAccount(kind, mode)
  }

  action accountActions = any {
    openAnyAccount,
    archive, restore, disable, supportReactivates, deleteInactiveDemo,
    openPosition, closePosition,
  }

  action paymentActions = any {
    deposit, verifyCard, requestWithdrawal, payWithdrawal, rejectWithdrawal, terminate,
  }

  action stepM1 = any { profileActions, stutter }
  action stepM2 = any { profileActions, accountActions, stutter }
  action stepM3 = any { profileActions, accountActions, paymentActions, stutter }
  action step = stepM3

  // ── invariants ──────────────────────────────────────────────────────────

  val fullTierMeansBothDocuments =
    client.tier == TFull implies (client.identityDoc == DApproved and client.addressDoc == DApproved)
  val bothDocumentsMeanFullTier =
    (client.identityDoc == DApproved and client.addressDoc == DApproved) implies client.tier == TFull
  val addressNeedsIdentity = client.addressDoc != DMissing implies client.identityDoc == DApproved
  val documentsNeedAProfile = client.identityDoc != DMissing implies client.onboarding == OProfile

  val balances = if (acct.present) acct.balance else 0
  val heldInPayouts = if (acct.present and acct.payout == PRequested) 1 else 0

  val depositsWithinTierLimit = and {
    client.tier == TNone implies client.deposited == 0,
    client.tier == TLow implies client.deposited <= 1,
    client.tier == THigher implies client.deposited <= 2,
  }
  val moneyIsConserved = client.deposited == balances + heldInPayouts + client.withdrawn
  val marginStaysCovered =
    (acct.present and acct.mode == MReal and acct.position) implies acct.balance >= 1
  val demoHoldsNoMoney = (acct.present and acct.mode == MDemo) implies acct.balance == 0
  val terminatedClientHoldsNoFunds =
    client.status == CTerminated implies (balances == 0 and heldInPayouts == 0)

  val profileInvariants = and {
    fullTierMeansBothDocuments, bothDocumentsMeanFullTier, addressNeedsIdentity, documentsNeedAProfile,
  }
  val allInvariants = and {
    profileInvariants,
    depositsWithinTierLimit, moneyIsConserved, marginStaysCovered, demoHoldsNoMoney,
    terminatedClientHoldsNoFunds,
  }

  // ── queries ─────────────────────────────────────────────────────────────
  // Unreachable(P) is the invariant not(P). Reachable(P) is checked by asking
  // for a violation of not(P): a counterexample is the witness.

  val noCentDemo = not(acct.present and acct.kind == KCent and acct.mode == MDemo)
  val gatedRegionDepositsOnlyWhenVerified =
    not(client.region == RDepositsGated and client.deposited >= 1 and client.tier != TFull)

  val notVerificationComplete = client.tier != TFull
  val notFinalRejection = client.identityDoc != DLocked
  val notArchivedAccount = not(acct.present and acct.status == AArchived)
  val notMoneyRoundTrip = client.withdrawn < 1

  // NoDeadEnd (AG EF goal) and DeadActions have no LTL/invariant form here;
  // see research/34 §8 D.

  // ── type invariant (for Apalache inductive checks) ──────────────────────

  pure val DOCS = Set(DMissing, DPending, DRejected, DLocked, DApproved)
  pure val BOOLS = Set(false, true)
  pure val MONEY = 0.to(MONEY_CAP)

  pure val ALL_CLIENTS = tuples(
    Set(CActive, CTerminated),
    Set(RStandard, RDepositsGated, RTradingGated),
    Set(ONew, OContacts, ODetails, OProfile),
    DOCS, 0.to(LAST_ATTEMPT), DOCS, 0.to(LAST_ATTEMPT),
    Set(TNone, TLow, THigher, TFull),
    BOOLS, BOOLS, MONEY, MONEY,
  ).map(t => {
    status: t._1, region: t._2, onboarding: t._3,
    identityDoc: t._4, identityFailures: t._5, addressDoc: t._6, addressFailures: t._7,
    tier: t._8, codeConfirmed: t._9, cardOk: t._10, deposited: t._11, withdrawn: t._12,
  })

  pure val ALL_ACCOUNTS = tuples(
    BOOLS, Set(KCent, KStandard, KProfessional), Set(MReal, MDemo),
    Set(AActive, AArchived, ADisabled), MONEY, BOOLS, Set(PNone, PRequested),
  ).map(t => {
    present: t._1, kind: t._2, mode: t._3, status: t._4,
    balance: t._5, position: t._6, payout: t._7,
  })

  // For Apalache inductive checks. With record sets built this way the
  // inductive step did not finish within 20 minutes (research/34 §8 D):
  // Apalache prefers one variable per field, plus a strengthening.
  val typeOK = client.in(ALL_CLIENTS) and acct.in(ALL_ACCOUNTS)

  // ── scenarios (a representative subset of the analint ones) ────────────

  action given(c: Client, a: Account): bool = all { client' = c, acct' = a }

  pure val lowTier = { ...newClient(RStandard), onboarding: ODetails, tier: TLow }
  pure val funded = { ...lowTier, deposited: 1 }
  pure val mainAccount = { ...ABSENT, present: true }

  run detailsRaiseTheTierTest =
    given({ ...newClient(RStandard), onboarding: OContacts }, ABSENT)
      .then(fillDetails)
      .expect(client.tier == TLow)

  run identityBeforeProfileIsRejectedTest =
    given(lowTier, ABSENT).then(submitIdentity).fail()

  run lastFailureLocksTheDocumentTest =
    given({ ...lowTier, onboarding: OProfile, identityDoc: DPending, identityFailures: 1 }, ABSENT)
      .then(lockIdentity)
      .expect(client.identityDoc == DLocked)

  run openRealStandardTest =
    given({ ...newClient(RStandard), onboarding: OContacts }, ABSENT)
      .then(openAccount(KStandard, MReal))
      .expect(acct.present and acct.kind == KStandard and acct.balance == 0)

  run archivedAccountCannotTradeTest =
    given(funded, { ...mainAccount, status: AArchived, balance: 1 }).then(openPosition).fail()

  run firstDepositAtLowTierTest =
    given(lowTier, mainAccount)
      .then(deposit)
      .expect(acct.balance == 1 and client.deposited == 1 and client.cardOk)

  run depositOverTierLimitIsRejectedTest =
    given(funded, { ...mainAccount, balance: 1 }).then(deposit).fail()

  run withdrawalWithoutCodeIsRejectedTest =
    given({ ...funded, cardOk: true }, { ...mainAccount, balance: 1 }).then(requestWithdrawal).fail()

  run withdrawalBeyondFreeMarginIsRejectedTest =
    given(
      { ...funded, cardOk: true, codeConfirmed: true },
      { ...mainAccount, balance: 1, position: true },
    ).then(requestWithdrawal).fail()

  run terminateWithMoneyIsRejectedTest =
    given(funded, { ...mainAccount, balance: 1 }).then(terminate).fail()

  run onboardingFlowTest =
    given(newClient(RStandard), ABSENT)
      .then(confirmContacts)
      .then(fillDetails)
      .then(completeProfile)
      .then(submitIdentity)
      .then(rejectIdentity)
      .then(submitIdentity)
      .then(approveIdentity)
      .expect(client.tier == THigher)
      .then(submitAddress)
      .then(approveAddress)
      .expect(client.tier == TFull)
}
