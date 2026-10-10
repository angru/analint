/**
 * Quint port of the broker M4 risk increment (benchmarks/broker/risk.py) for
 * the research/34 §8 B2 cross-check. It extends examples/broker/broker.qnt
 * (M1–M3) with the same abstraction and bounds as the analint model; the
 * analint kernel's implicit rules are written out explicitly:
 *
 *  - presence: risk-account and order slots are records with `present`; an
 *    absent slot holds canonical (default) values, as analint's state key
 *    ignores absent fields; Create needs an absent slot, Set/Delete a present
 *    one (every action's guard already implies this);
 *  - quantifiers and Count range over present members only;
 *  - Param `where` filters become the fixed slot → owner pairing;
 *  - Capacity is the constant 1 account / 1 order of M4;
 *  - a safety-preserving stutter keeps quiescent states from being deadlocks.
 *
 *   quint typecheck benchmarks/broker/risk.qnt
 *   quint verify benchmarks/broker/risk.qnt --main=risk --backend=tlc \
 *     --init=initRiskOnly --step=stepRiskOnly --invariant=riskInvariants
 *   quint verify benchmarks/broker/risk.qnt --main=risk --backend=tlc \
 *     --init=initM4 --step=stepM4 --invariant=allM4Invariants
 *
 * The risk increment alone (client registered, active and unchanged; three
 * regions) has 54,084 distinct states in both tools (research/34 §8 B2).
 */
module risk {
  import broker.* from "../../examples/broker/broker"

  type Equity = ESmall | ELarge | EZero | ENegative
  type Leverage = LCapped | LUncapped
  type Cap = CapLow | CapHigh
  type MarginLevel = MHealthy | MCall | MStop
  type Protection = PrNone | PrDue | PrPaid
  type Owner = OwPrimary | OwSecondary
  type OStatus = OOpen | OClosed | OStopped
  type RSlot = RPrimary | RSecondary
  type OSlot = OFirst | OSecond

  type RiskAccount = {
    present: bool,
    kind: Kind,
    equity: Equity,
    leverage: Leverage,
    cap: Cap,
    margin: MarginLevel,
    fullyStopped: bool,
    protection: Protection,
  }

  type Order = { present: bool, owner: Owner, profit: int, status: OStatus }

  pure val ACCOUNT_CAPACITY = 1
  pure val ORDER_CAPACITY = 1
  pure val RSLOTS = Set(RPrimary, RSecondary)
  pure val OSLOTS = Set(OFirst, OSecond)
  pure val KINDS = Set(KCent, KStandard, KProfessional)
  pure val EQUITIES = Set(ESmall, ELarge, EZero, ENegative)
  pure val MARGINS = Set(MHealthy, MCall, MStop)
  pure val PROFITS = (-1).to(1)

  pure val NO_RISK: RiskAccount = {
    present: false,
    kind: KStandard,
    equity: ESmall,
    leverage: LCapped,
    cap: CapLow,
    margin: MHealthy,
    fullyStopped: false,
    protection: PrNone,
  }
  pure val NO_ORDER: Order = { present: false, owner: OwPrimary, profit: 0, status: OOpen }

  // the Param where= pairing of an account slot with its order owner
  pure def ownerOf(slot: RSlot): Owner = if (slot == RPrimary) OwPrimary else OwSecondary

  var risk: RSlot -> RiskAccount
  var orders: OSlot -> Order
  var completedTrade: bool
  var highMargin: bool

  // ── helpers ─────────────────────────────────────────────────────────────

  val activeClient = client.status == CActive
  val presentAccounts = RSLOTS.filter(s => risk.get(s).present).size()
  def isOpen(o: OSlot): bool = orders.get(o).present and orders.get(o).status == OOpen
  val openOrders = OSLOTS.filter(o => isOpen(o)).size()
  def ownedOpen(owner: Owner): int =
    OSLOTS.filter(o => isOpen(o) and orders.get(o).owner == owner).size()

  action riskStep(r: RSlot -> RiskAccount, o: OSlot -> Order, trade: bool, high: bool): bool =
    all {
      risk' = r,
      orders' = o,
      completedTrade' = trade,
      highMargin' = high,
      client' = client,
      acct' = acct,
    }

  action setAccount(slot: RSlot, a: RiskAccount): bool =
    riskStep(risk.set(slot, a), orders, completedTrade, highMargin)

  action riskUnchanged = all {
    risk' = risk,
    orders' = orders,
    completedTrade' = completedTrade,
    highMargin' = highMargin,
  }

  // ── M4 actions ──────────────────────────────────────────────────────────

  action openRiskAccount(slot: RSlot, kind: Kind): bool = all {
    activeClient,
    client.onboarding != ONew,
    presentAccounts < ACCOUNT_CAPACITY,
    not(risk.get(slot).present),
    setAccount(slot, { ...NO_RISK, present: true, kind: kind }),
  }

  action openOrder(slot: RSlot, o: OSlot, profit: int): bool = {
    val a = risk.get(slot)
    all {
      activeClient,
      a.present,
      not(orders.get(o).present),
      a.equity == ESmall,
      a.margin == MHealthy,
      a.protection == PrNone,
      openOrders < ORDER_CAPACITY,
      riskStep(
        risk.set(slot, { ...a, fullyStopped: false }),
        orders.set(o, { present: true, owner: ownerOf(slot), profit: profit, status: OOpen }),
        completedTrade,
        highMargin,
      ),
    }
  }

  action closeOrder(slot: RSlot, o: OSlot): bool = all {
    activeClient,
    risk.get(slot).present,
    isOpen(o),
    orders.get(o).owner == ownerOf(slot),
    risk.get(slot).margin != MStop,
    riskStep(risk, orders.set(o, { ...orders.get(o), status: OClosed }), true, highMargin),
  }

  action reclaimOrder(o: OSlot): bool = all {
    orders.get(o).present,
    orders.get(o).status != OOpen,
    riskStep(risk, orders.set(o, NO_ORDER), completedTrade, highMargin),
  }

  action chooseUncapped(slot: RSlot): bool = {
    val a = risk.get(slot)
    all {
      activeClient,
      a.present,
      a.equity == ESmall,
      completedTrade,
      not(highMargin),
      setAccount(slot, { ...a, leverage: LUncapped, cap: CapHigh }),
    }
  }

  action lowerCap(slot: RSlot): bool = all {
    risk.get(slot).present,
    risk.get(slot).cap == CapHigh,
    setAccount(slot, { ...risk.get(slot), cap: CapLow }),
  }

  action startHighMargin = all {
    not(highMargin),
    RSLOTS.forall(s => risk.get(s).present implies risk.get(s).cap == CapLow),
    riskStep(risk, orders, completedTrade, true),
  }

  action endHighMargin = all {
    highMargin,
    riskStep(risk, orders, completedTrade, false),
  }

  action marketMoves(slot: RSlot, equity: Equity, margin: MarginLevel): bool = {
    val a = risk.get(slot)
    all {
      equity == ENegative implies margin == MStop,
      a.present,
      ownedOpen(ownerOf(slot)) > 0,
      a.protection == PrNone,
      equity == EZero implies margin != MHealthy,
      (a.kind == KCent and equity == EZero) implies margin == MStop,
      setAccount(
        slot,
        { ...a, equity: equity, margin: margin, leverage: LCapped, cap: CapLow },
      ),
    }
  }

  action stopWorstOrder(slot: RSlot, o: OSlot): bool = {
    val owner = ownerOf(slot)
    all {
      risk.get(slot).present,
      isOpen(o),
      orders.get(o).owner == owner,
      risk.get(slot).margin == MStop,
      OSLOTS.forall(other =>
        (isOpen(other) and orders.get(other).owner == owner)
          implies orders.get(o).profit <= orders.get(other).profit
      ),
      riskStep(risk, orders.set(o, { ...orders.get(o), status: OStopped }), completedTrade, highMargin),
    }
  }

  action finishNegativeStop(slot: RSlot): bool = {
    val a = risk.get(slot)
    all {
      a.present,
      a.equity == ENegative,
      a.margin == MStop,
      a.protection == PrNone,
      ownedOpen(ownerOf(slot)) == 0,
      setAccount(slot, { ...a, fullyStopped: true, protection: PrDue }),
    }
  }

  action protectNegativeBalance(slot: RSlot): bool = {
    val a = risk.get(slot)
    all {
      a.present,
      a.fullyStopped,
      a.equity == ENegative,
      a.protection == PrDue,
      ownedOpen(ownerOf(slot)) == 0,
      setAccount(slot, { ...a, equity: EZero, margin: MHealthy, protection: PrPaid }),
    }
  }

  action recapitalize(slot: RSlot): bool = {
    val a = risk.get(slot)
    all {
      activeClient,
      a.present,
      a.protection == PrPaid,
      setAccount(slot, { ...a, equity: ESmall, protection: PrNone, fullyStopped: false }),
    }
  }

  // parameters are chosen per action: one shared set of nondet choices made
  // TLC enumerate every combination for every action (~900 successors per
  // distinct state)
  action riskActions = any {
    { nondet slot = RSLOTS.oneOf() nondet kind = KINDS.oneOf() openRiskAccount(slot, kind) },
    {
      nondet slot = RSLOTS.oneOf()
      nondet o = OSLOTS.oneOf()
      nondet profit = PROFITS.oneOf()
      openOrder(slot, o, profit)
    },
    { nondet slot = RSLOTS.oneOf() nondet o = OSLOTS.oneOf() closeOrder(slot, o) },
    { nondet o = OSLOTS.oneOf() reclaimOrder(o) },
    { nondet slot = RSLOTS.oneOf() chooseUncapped(slot) },
    { nondet slot = RSLOTS.oneOf() lowerCap(slot) },
    startHighMargin,
    endHighMargin,
    {
      nondet slot = RSLOTS.oneOf()
      nondet equity = EQUITIES.oneOf()
      nondet margin = MARGINS.oneOf()
      marketMoves(slot, equity, margin)
    },
    { nondet slot = RSLOTS.oneOf() nondet o = OSLOTS.oneOf() stopWorstOrder(slot, o) },
    { nondet slot = RSLOTS.oneOf() finishNegativeStop(slot) },
    { nondet slot = RSLOTS.oneOf() protectNegativeBalance(slot) },
    { nondet slot = RSLOTS.oneOf() recapitalize(slot) },
  }

  // ── initial states and steps ────────────────────────────────────────────

  // (inlined in both: the TLC translation rejects an action shared by inits)
  pure val NO_RISKS = RSLOTS.mapBy(_ => NO_RISK)
  pure val NO_ORDERS = OSLOTS.mapBy(_ => NO_ORDER)

  // M4: the M3 initial states with absent risk slots
  action initM4 = all {
    init,
    risk' = NO_RISKS,
    orders' = NO_ORDERS,
    completedTrade' = false,
    highMargin' = false,
  }

  // the risk increment alone: a registered, active client nothing changes
  action initRiskOnly = all {
    nondet region = Set(RStandard, RDepositsGated, RTradingGated).oneOf()
    all {
      client' = { ...newClient(region), onboarding: OContacts },
      acct' = ABSENT,
      risk' = NO_RISKS,
      orders' = NO_ORDERS,
      completedTrade' = false,
      highMargin' = false,
    }
  }

  action stepM4 = any { all { stepM3, riskUnchanged }, riskActions }
  action stepRiskOnly = any { riskActions, all { client' = client, acct' = acct, riskUnchanged } }

  // ── invariants ──────────────────────────────────────────────────────────

  val uncappedRequiresEligibility = RSLOTS.forall(s => {
    val a = risk.get(s)
    (a.present and a.leverage == LUncapped) implies (a.equity == ESmall and completedTrade)
  })
  val highMarginCapsLeverage =
    highMargin implies RSLOTS.forall(s => risk.get(s).present implies risk.get(s).cap == CapLow)
  val protectionRequiresFullStop = RSLOTS.forall(s => {
    val a = risk.get(s)
    (a.present and a.protection == PrPaid) implies (a.fullyStopped and a.equity == EZero)
  })
  val portfolioCapacityIsRespected =
    presentAccounts <= ACCOUNT_CAPACITY and openOrders <= ORDER_CAPACITY

  val riskInvariants = and {
    uncappedRequiresEligibility, highMarginCapsLeverage, protectionRequiresFullStop,
    portfolioCapacityIsRespected,
  }
  val allM4Invariants = allInvariants and riskInvariants
}
