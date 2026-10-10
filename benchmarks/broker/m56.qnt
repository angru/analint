/**
 * The broker M5 and M6 compositions in Quint, and two couplings small enough
 * to check exhaustively (research/34 §8 B2). Built from the increment ports:
 * examples/broker/broker.qnt (M1–M3), risk.qnt (M4), partners.qnt (M5),
 * methods.qnt (M6).
 *
 *  - `m5`: M3 × risk (one account, one order) × partners, as m5.py;
 *  - `m6`: M5 × payment methods with capacities 2/2/2, as m6.py;
 *  - `profilePartners`: the client profile (M1) × partners — their coupling
 *    is the shared one-time security code (m5_profile_partners.py);
 *  - `profileMethods`: the client profile (M1) × payment methods — the tier and
 *    region gate funding (m6_profile_methods.py).
 *
 * The full M5/M6 products are far past exhaustive checking in either tool
 * (M4 alone is 286,428,912 states in TLC); they are checked by random
 * simulation here. The couplings are checked exhaustively and must find
 * analint's distinct-state counts:
 *
 *   quint verify benchmarks/broker/m56.qnt --main=profilePartners --backend=tlc \
 *     --init=initProfilePartners --step=stepProfilePartners --invariant=couplingInvariants
 *   quint verify benchmarks/broker/m56.qnt --main=profileMethods --backend=tlc \
 *     --init=initProfileMethods --step=stepProfileMethods --invariant=couplingInvariants
 *   quint run benchmarks/broker/m56.qnt --main=m6 --init=initM6 --step=stepM6 \
 *     --invariant=m6Invariants --max-samples=2000 --max-steps=40
 */
module m5 {
  import broker.* from "../../examples/broker/broker"
  import risk.* from "./risk"
  import partners.* from "./partners"

  action initM5 = all {
    initM4,
    partner' = NEW_PARTNER,
    attributed' = false,
    wallet' = EMPTY_WALLET,
  }

  action stepM5 = any {
    all { stepM3, riskUnchanged, partnersUnchanged },
    all { riskActions, partnersUnchanged },
    all { partnerActions, riskUnchanged },
  }

  val m5Invariants = allM4Invariants and rewardsAreConserved
}

module m6 {
  import broker.* from "../../examples/broker/broker"
  import risk.* from "./risk"
  import partners.* from "./partners"
  import methods.* from "./methods"

  action initM6 = all {
    init,
    risk' = NO_RISKS,
    orders' = NO_ORDERS,
    completedTrade' = false,
    highMargin' = false,
    accountCapacity' = 2,
    orderCapacity' = 2,
    partner' = NEW_PARTNER,
    attributed' = false,
    wallet' = EMPTY_WALLET,
    slots' = SLOTS.mapBy(_ => NO_METHOD),
    ledger' = NEW_LEDGER,
  }

  action stepM6 = any {
    all { stepM3, riskUnchanged, partnersUnchanged, methodsUnchanged },
    all { riskActions, partnersUnchanged, methodsUnchanged },
    all { partnerActions, riskUnchanged, methodsUnchanged },
    all { methodActions, riskUnchanged, partnersUnchanged },
  }

  val m6Invariants = allM4Invariants and rewardsAreConserved and methodInvariants
}

module profilePartners {
  import broker.* from "../../examples/broker/broker"
  import partners.* from "./partners"

  action initProfilePartners = all {
    init,
    partner' = NEW_PARTNER,
    attributed' = false,
    wallet' = EMPTY_WALLET,
  }

  action stepProfilePartners = any {
    all { stepM1, partnersUnchanged },
    partnerActions,
  }

  val couplingInvariants = profileInvariants and rewardsAreConserved
}

module profileMethods {
  import broker.* from "../../examples/broker/broker"
  import methods.* from "./methods"

  action initProfileMethods = all {
    init,
    slots' = SLOTS.mapBy(_ => NO_METHOD),
    ledger' = NEW_LEDGER,
  }

  action stepProfileMethods = any {
    all { stepM1, methodsUnchanged },
    methodActions,
  }

  val couplingInvariants = profileInvariants and methodInvariants
}
