"""M6: two payment-method slots sharing a small, separate settlement ledger.

This ledger represents the new rails only, without counting M3 cash twice.
The payout request has no cancel action; only settlement or rejection refunds it.
"""

from enum import StrEnum

from examples.broker.domain import Client, ClientStatus, DocStatus, Onboarding, Region, Tier

from analint import (
    Absent,
    Action,
    Add,
    And,
    Bound,
    Contract,
    Count,
    Create,
    Entity,
    Expect,
    Field,
    ForAll,
    Implies,
    Invariant,
    Lifecycle,
    Not,
    Param,
    Present,
    Reachable,
    Scenario,
    Scope,
    Set,
    Subtract,
    Sum,
)

from .domain import BENCH_BUDGET, Capacity


class Currency(StrEnum):
    UNIT = "unit"
    OTHER = "other"


class MethodKind(StrEnum):
    CARD = "card"
    BANK = "bank"


class RequestStatus(StrEnum):
    IDLE = "idle"
    REQUESTED = "requested"


class PaymentMethod(Entity):
    kind: MethodKind = MethodKind.CARD
    currency: Currency = Currency.UNIT
    own_name: bool = True
    eligible: bool = False
    held: int = Field(0, ge=0, le=1)
    request: RequestStatus = Lifecycle(
        RequestStatus.IDLE,
        transitions={
            RequestStatus.IDLE: [RequestStatus.REQUESTED],
            RequestStatus.REQUESTED: [RequestStatus.IDLE],
        },
    )


class MethodLedger(Entity):
    currency: Currency = Currency.UNIT
    funded: int = Field(0, ge=0, le=2)
    balance: int = Field(0, ge=0, le=2)
    paid: int = Field(0, ge=0, le=2)


methods = Scope(PaymentMethod, keys=["card", "bank"])
method = Param("method", methods)
kind = Param("kind", MethodKind)
currency = Param("currency", Currency)
own_name = Param("own_name", bool)
each = Bound("method", methods)
card, bank = methods["card"], methods["bank"]
active_client = Client.status == ClientStatus.ACTIVE

register_method = Action(
    params=[method, kind, currency, own_name],
    pre=[active_client, Count(each, Present(each)) < Capacity.methods],
    effect=[Create(method, kind=kind, currency=currency, own_name=own_name)],
)
fund_by_method = Action(
    params=[method],
    pre=[
        active_client,
        Present(method),
        method.own_name,
        method.currency == MethodLedger.currency,
        MethodLedger.funded < 2,
        Client.tier != Tier.NONE,
        Implies(Client.region == Region.DEPOSITS_GATED, Client.tier == Tier.FULL),
    ],
    effect=[Add(MethodLedger.funded, 1), Add(MethodLedger.balance, 1), Set(method.eligible, True)],
)
request_method_payout = Action(
    params=[method],
    pre=[
        active_client,
        Present(method),
        Client.code_confirmed,
        method.own_name,
        method.eligible,
        method.currency == MethodLedger.currency,
        method.request == RequestStatus.IDLE,
        MethodLedger.balance >= 1,
    ],
    effect=[
        Subtract(MethodLedger.balance, 1),
        Set(method.held, 1),
        Set(method.request, RequestStatus.REQUESTED),
        Set(Client.code_confirmed, False),
    ],
)
settle_method_payout = Action(
    params=[method],
    pre=[Present(method), method.request == RequestStatus.REQUESTED],
    effect=[
        Set(method.held, 0),
        Set(method.request, RequestStatus.IDLE),
        Add(MethodLedger.paid, 1),
    ],
)
reject_method_payout = Action(
    params=[method],
    pre=[Present(method), method.request == RequestStatus.REQUESTED],
    effect=[
        Set(method.held, 0),
        Set(method.request, RequestStatus.IDLE),
        Add(MethodLedger.balance, 1),
    ],
)
method_money_is_conserved = Invariant(
    MethodLedger.funded == MethodLedger.balance + MethodLedger.paid + Sum(each, each.held),
)
method_request_matches_hold = Invariant(
    ForAll(
        each,
        And(
            Implies(each.request == RequestStatus.IDLE, each.held == 0),
            Implies(each.request == RequestStatus.REQUESTED, each.held == 1),
        ),
    ),
)
method_capacity_is_respected = Invariant(Count(each, Present(each)) <= Capacity.methods)
two_methods_can_hold_payouts = Reachable(
    Count(each, each.request == RequestStatus.REQUESTED) == 2,
    max_states=BENCH_BUDGET,
)

_verified = Client(
    onboarding=Onboarding.PROFILE,
    identity_doc=DocStatus.APPROVED,
    address_doc=DocStatus.APPROVED,
    tier=Tier.FULL,
    code_confirmed=True,
)
sc_register_payment_method = Scenario(
    action=register_method.bind(
        method=card, kind=MethodKind.CARD, currency=Currency.UNIT, own_name=True
    ),
    given=[Client(), Capacity(methods=2), Absent(card), Absent(bank)],
    then=[Present(card)],
)
sc_third_party_funding_is_rejected = Scenario(
    action=fund_by_method.bind(method=card),
    given=[_verified, MethodLedger(), card(own_name=False), Absent(bank)],
    expected=Expect.FAIL,
)
sc_wrong_currency_funding_is_rejected = Scenario(
    action=fund_by_method.bind(method=card),
    given=[_verified, MethodLedger(), card(currency=Currency.OTHER), Absent(bank)],
    expected=Expect.FAIL,
)
sc_method_funding_makes_payout_eligible = Scenario(
    action=fund_by_method.bind(method=card),
    given=[_verified, MethodLedger(), card(), Absent(bank)],
    then=[card.eligible, MethodLedger.balance == 1],
)
sc_method_payout_consumes_code = Scenario(
    action=request_method_payout.bind(method=card),
    given=[_verified, MethodLedger(funded=1, balance=1), card(eligible=True), Absent(bank)],
    then=[card.held == 1, MethodLedger.balance == 0, Not(Client.code_confirmed)],
)
sc_method_payout_without_code_is_rejected = Scenario(
    action=request_method_payout.bind(method=card),
    given=[Client(), MethodLedger(funded=1, balance=1), card(eligible=True), Absent(bank)],
    expected=Expect.FAIL,
)
sc_wrong_currency_payout_is_rejected = Scenario(
    action=request_method_payout.bind(method=card),
    given=[
        _verified,
        MethodLedger(funded=1, balance=1),
        card(eligible=True, currency=Currency.OTHER),
        Absent(bank),
    ],
    expected=Expect.FAIL,
)
sc_settlement_pays_held_funds = Scenario(
    action=settle_method_payout.bind(method=card),
    given=[
        MethodLedger(funded=1),
        card(eligible=True, held=1, request=RequestStatus.REQUESTED),
        Absent(bank),
    ],
    then=[MethodLedger.paid == 1, card.held == 0],
)
sc_rejection_refunds_held_funds = Scenario(
    action=reject_method_payout.bind(method=card),
    given=[
        MethodLedger(funded=1),
        card(eligible=True, held=1, request=RequestStatus.REQUESTED),
        Absent(bank),
    ],
    then=[MethodLedger.balance == 1, card.held == 0],
)

payment_methods = Contract(
    id="payment_methods",
    name="Bounded payment rails",
    entities=[Client, Capacity, PaymentMethod, MethodLedger],
    scopes=[methods],
    actions=[
        register_method,
        fund_by_method,
        request_method_payout,
        settle_method_payout,
        reject_method_payout,
    ],
    invariants=[
        method_money_is_conserved,
        method_request_matches_hold,
        method_capacity_is_respected,
    ],
    queries=[two_methods_can_hold_payouts],
    scenarios=[
        sc_register_payment_method,
        sc_third_party_funding_is_rejected,
        sc_wrong_currency_funding_is_rejected,
        sc_method_funding_makes_payout_eligible,
        sc_method_payout_consumes_code,
        sc_method_payout_without_code_is_rejected,
        sc_wrong_currency_payout_is_rejected,
        sc_settlement_pays_held_funds,
        sc_rejection_refunds_held_funds,
    ],
)
