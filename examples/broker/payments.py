"""Increment M3 — payments: deposits, withdrawals and closing the profile.

Deposits go to an active real account, up to the cumulative limit of the
client's verification tier; a deposit also makes the card eligible for payouts.
A withdrawal needs a fresh security code, an eligible card and free margin; once
requested it cannot be cancelled — it is paid out, or rejected and refunded.
A client may close the profile only with no money left in the model.
"""

from analint import (
    Absent,
    Action,
    Add,
    And,
    Bound,
    Contract,
    Count,
    Expect,
    ForAll,
    Implies,
    Invariant,
    Not,
    Or,
    Param,
    Present,
    Reachable,
    Scenario,
    Set,
    Subtract,
    Sum,
    Unreachable,
)

from .domain import (
    BUDGET,
    MONEY_CAP,
    Account,
    AccountStatus,
    Client,
    ClientStatus,
    Mode,
    Onboarding,
    Payout,
    Region,
    Tier,
    accounts,
)

acct = Param("acct", accounts)
some = Bound("account", accounts)

client_is_active = Client.status == ClientStatus.ACTIVE
within_tier_limit = Or(
    And(Client.tier == Tier.LOW, Client.deposited < 1),
    And(Client.tier == Tier.HIGHER, Client.deposited < 2),
    And(Client.tier == Tier.FULL, Client.deposited < MONEY_CAP),
)
held_in_payouts = Count(some, some.payout == Payout.REQUESTED)  # 1 unit each
balances = Sum(some, some.balance)

# ── deposits ─────────────────────────────────────────────────────────────────

deposit = Action(
    name="Deposit one unit by card",
    params=[acct],
    pre=[
        Present(acct),
        client_is_active,
        acct.mode == Mode.REAL,
        acct.status == AccountStatus.ACTIVE,
        within_tier_limit,
        Implies(Client.region == Region.DEPOSITS_GATED, Client.tier == Tier.FULL),
    ],
    effect=[Add(acct.balance, 1), Add(Client.deposited, 1), Set(Client.card_ok, True)],
    post=[acct.status == AccountStatus.ACTIVE],  # P3: money moves only on active accounts
)

verify_card = Action(
    name="The client verifies a card for payouts",
    pre=[Not(Client.card_ok)],
    effect=[Set(Client.card_ok, True)],
)

# ── withdrawals ──────────────────────────────────────────────────────────────

request_withdrawal = Action(
    name="Request a withdrawal of one unit",
    params=[acct],
    pre=[
        Present(acct),
        client_is_active,
        Client.code_confirmed,  # P8: a fresh security code
        Client.card_ok,
        acct.mode == Mode.REAL,
        acct.status == AccountStatus.ACTIVE,
        acct.payout == Payout.NONE,
        acct.balance >= 1,
        Implies(acct.position, acct.balance >= 2),  # free margin covers the payout
    ],
    effect=[
        Subtract(acct.balance, 1),
        Set(acct.payout, Payout.REQUESTED),
        Set(Client.code_confirmed, False),  # the code is spent
    ],
    post=[acct.status == AccountStatus.ACTIVE],
)

pay_withdrawal = Action(
    name="The payment provider pays a requested withdrawal out",
    params=[acct],
    pre=[Present(acct), acct.payout == Payout.REQUESTED],
    effect=[Set(acct.payout, Payout.NONE), Add(Client.withdrawn, 1)],
)

reject_withdrawal = Action(
    name="A requested withdrawal is rejected and refunded",
    params=[acct],
    pre=[Present(acct), acct.payout == Payout.REQUESTED],
    effect=[Set(acct.payout, Payout.NONE), Add(acct.balance, 1)],
)

# ── closing the profile ──────────────────────────────────────────────────────

terminate = Action(
    name="The client closes the profile",
    pre=[
        client_is_active,
        ForAll(some, And(some.balance == 0, some.payout == Payout.NONE, Not(some.position))),
    ],
    effect=[Set(Client.status, ClientStatus.TERMINATED)],
)

# ── invariants ───────────────────────────────────────────────────────────────

# P1: cumulative deposits never exceed the tier's limit
deposits_within_tier_limit = Invariant(
    And(
        Implies(Client.tier == Tier.NONE, Client.deposited == 0),
        Implies(Client.tier == Tier.LOW, Client.deposited <= 1),
        Implies(Client.tier == Tier.HIGHER, Client.deposited <= 2),
    ),
    label="deposits never exceed the verification tier's limit",
)

money_is_conserved = Invariant(
    Client.deposited == balances + held_in_payouts + Client.withdrawn,
    label="deposited = balances + payouts in flight + paid out",
)

# P2: a withdrawal never takes the margin of an open position
margin_stays_covered = Invariant(
    ForAll(some, Implies(And(some.mode == Mode.REAL, some.position), some.balance >= 1)),
    label="an open real position always keeps its margin",
)

demo_holds_no_money = Invariant(
    ForAll(some, Implies(some.mode == Mode.DEMO, some.balance == 0)),
    label="demo accounts never hold real money",
)

terminated_client_holds_no_funds = Invariant(
    Implies(Client.status == ClientStatus.TERMINATED, And(balances == 0, held_in_payouts == 0)),
    label="a closed profile holds no money",
)

# ── queries ──────────────────────────────────────────────────────────────────

money_round_trip = Reachable(Client.withdrawn >= 1, max_states=BUDGET)
gated_region_deposits_only_when_verified = Unreachable(
    And(
        Client.region == Region.DEPOSITS_GATED,
        Client.deposited >= 1,
        Client.tier != Tier.FULL,
    ),
    max_states=BUDGET,
)

# ── scenarios ────────────────────────────────────────────────────────────────

main = accounts["main"]
_low_tier = Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW)

sc_first_deposit_at_low_tier = Scenario(
    name="A LOW-tier client deposits within the limit",
    action=deposit.bind(acct=main),
    given=[_low_tier, main()],
    then=[main.balance == 1, Client.deposited == 1, Client.card_ok],
)

sc_deposit_over_tier_limit_is_rejected = Scenario(
    name="A LOW-tier client cannot deposit beyond the limit",
    action=deposit.bind(acct=main),
    given=[Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW, deposited=1), main(balance=1)],
    expected=Expect.FAIL,
)

sc_deposit_into_archived_account_is_rejected = Scenario(
    name="An archived account accepts no deposits",
    action=deposit.bind(acct=main),
    given=[_low_tier, main(status=AccountStatus.ARCHIVED)],
    expected=Expect.FAIL,
)

sc_gated_region_needs_full_verification_to_deposit = Scenario(
    name="In a deposits-gated region only a fully verified client deposits",
    action=deposit.bind(acct=main),
    given=[
        Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW, region=Region.DEPOSITS_GATED),
        main(),
    ],
    expected=Expect.FAIL,
)

sc_verify_card = Scenario(
    name="A verified card can receive payouts",
    action=verify_card,
    given=[Client()],
    then=[Client.card_ok],
)

_ready_to_withdraw = Client(
    onboarding=Onboarding.DETAILS, tier=Tier.LOW, deposited=1, card_ok=True, code_confirmed=True
)

sc_withdrawal_spends_the_code = Scenario(
    name="A withdrawal holds the unit and spends the security code",
    action=request_withdrawal.bind(acct=main),
    given=[_ready_to_withdraw, main(balance=1)],
    then=[main.payout == Payout.REQUESTED, main.balance == 0, Not(Client.code_confirmed)],
)

sc_withdrawal_without_code_is_rejected = Scenario(
    name="A withdrawal without a fresh security code is rejected",
    action=request_withdrawal.bind(acct=main),
    given=[
        Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW, deposited=1, card_ok=True),
        main(balance=1),
    ],
    expected=Expect.FAIL,
)

sc_withdrawal_to_ineligible_card_is_rejected = Scenario(
    name="A payout needs a card used for a deposit or verified",
    action=request_withdrawal.bind(acct=main),
    given=[
        Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW, deposited=1, code_confirmed=True),
        main(balance=1),
    ],
    expected=Expect.FAIL,
)

sc_withdrawal_beyond_free_margin_is_rejected = Scenario(
    name="A withdrawal cannot take the margin of an open position",
    action=request_withdrawal.bind(acct=main),
    given=[_ready_to_withdraw, main(balance=1, position=True)],
    expected=Expect.FAIL,
)

_payout_in_flight = [
    Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW, deposited=1, card_ok=True),
    main(payout=Payout.REQUESTED),
]

sc_pay_withdrawal = Scenario(
    name="A requested withdrawal is paid out",
    action=pay_withdrawal.bind(acct=main),
    given=_payout_in_flight,
    then=[main.payout == Payout.NONE, Client.withdrawn == 1],
)

sc_reject_withdrawal_refunds = Scenario(
    name="A rejected withdrawal is refunded to the account",
    action=reject_withdrawal.bind(acct=main),
    given=_payout_in_flight,
    then=[main.payout == Payout.NONE, main.balance == 1],
)

sc_terminate_empty_profile = Scenario(
    name="A client without money closes the profile",
    action=terminate,
    given=[Client(onboarding=Onboarding.CONTACTS), Absent(main)],
    then=[Client.status == ClientStatus.TERMINATED],
)

sc_terminate_with_money_is_rejected = Scenario(
    name="A profile with money left cannot be closed",
    action=terminate,
    given=[Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW, deposited=1), main(balance=1)],
    expected=Expect.FAIL,
)

payments = Contract(
    id="payments",
    name="Deposits, withdrawals and closing the profile",
    entities=[Client, Account],
    scopes=[accounts],
    actions=[
        deposit,
        verify_card,
        request_withdrawal,
        pay_withdrawal,
        reject_withdrawal,
        terminate,
    ],
    invariants=[
        deposits_within_tier_limit,
        money_is_conserved,
        margin_stays_covered,
        demo_holds_no_money,
        terminated_client_holds_no_funds,
    ],
    queries=[money_round_trip, gated_region_deposits_only_when_verified],
    scenarios=[
        sc_first_deposit_at_low_tier,
        sc_deposit_over_tier_limit_is_rejected,
        sc_deposit_into_archived_account_is_rejected,
        sc_gated_region_needs_full_verification_to_deposit,
        sc_verify_card,
        sc_withdrawal_spends_the_code,
        sc_withdrawal_without_code_is_rejected,
        sc_withdrawal_to_ineligible_card_is_rejected,
        sc_withdrawal_beyond_free_margin_is_rejected,
        sc_pay_withdrawal,
        sc_reject_withdrawal_refunds,
        sc_terminate_empty_profile,
        sc_terminate_with_money_is_rejected,
    ],
)
