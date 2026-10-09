"""Increment M2 — trading accounts: opening, archiving, disabling, positions.

An account's class and mode are fixed when it is opened; demo is not offered for
the cent class. A real account is archived after inactivity (or by the client)
and restored on request; compliance may disable it and only support reactivates
it. An inactive demo account is deleted. Only an active account trades.
"""

from analint import (
    Absent,
    Action,
    And,
    Bound,
    Contract,
    Create,
    Delete,
    Exists,
    Expect,
    Implies,
    Not,
    Or,
    Param,
    Present,
    Reachable,
    Scenario,
    Set,
    Unreachable,
)

from .domain import (
    BUDGET,
    Account,
    AccountKind,
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
kind = Param("kind", AccountKind)
mode = Param("mode", Mode)
some = Bound("account", accounts)

client_is_active = Client.status == ClientStatus.ACTIVE
registered = Client.onboarding != Onboarding.NEW

# ── opening and lifecycle ────────────────────────────────────────────────────

open_account = Action(
    name="Open a trading account",
    params=[acct, kind, mode],
    where=[Not(And(kind == AccountKind.CENT, mode == Mode.DEMO))],  # no cent demo
    pre=[client_is_active, registered],
    effect=[Create(acct, kind=kind, mode=mode)],
)

archive = Action(
    name="Archive a real account (inactivity or the client's choice)",
    params=[acct],
    pre=[
        Present(acct),
        acct.mode == Mode.REAL,
        acct.status == AccountStatus.ACTIVE,
        Not(acct.position),
        acct.payout == Payout.NONE,
    ],
    effect=[Set(acct.status, AccountStatus.ARCHIVED)],
)

restore = Action(
    name="The client restores an archived account",
    params=[acct],
    pre=[Present(acct), client_is_active, acct.status == AccountStatus.ARCHIVED],
    effect=[Set(acct.status, AccountStatus.ACTIVE)],
)

disable = Action(
    name="Compliance disables a real account",
    params=[acct],
    pre=[Present(acct), acct.mode == Mode.REAL, acct.status == AccountStatus.ACTIVE],
    effect=[Set(acct.status, AccountStatus.DISABLED)],
)

support_reactivates = Action(
    name="Support reactivates a disabled account",
    params=[acct],
    pre=[Present(acct), client_is_active, acct.status == AccountStatus.DISABLED],
    effect=[Set(acct.status, AccountStatus.ACTIVE)],
)

delete_inactive_demo = Action(
    name="An inactive demo account is deleted",
    params=[acct],
    pre=[
        Present(acct),
        acct.mode == Mode.DEMO,
        acct.status == AccountStatus.ACTIVE,
        Not(acct.position),
    ],
    effect=[Delete(acct)],
)

# ── trading (only an active account trades: P3 is stated as a postcondition) ─

open_position = Action(
    name="Open a position",
    params=[acct],
    pre=[
        Present(acct),
        client_is_active,
        acct.status == AccountStatus.ACTIVE,
        Not(acct.position),
        Or(acct.mode == Mode.DEMO, acct.balance >= 1),  # 1 unit of margin on a real account
        Implies(
            And(Client.region == Region.TRADING_GATED, acct.mode == Mode.REAL),
            Client.tier == Tier.FULL,
        ),
    ],
    effect=[Set(acct.position, True)],
    post=[acct.status == AccountStatus.ACTIVE],
)

close_position = Action(
    name="Close a position",
    params=[acct],
    pre=[Present(acct), client_is_active, acct.status == AccountStatus.ACTIVE, acct.position],
    effect=[Set(acct.position, False)],
    post=[acct.status == AccountStatus.ACTIVE],
)

# ── queries ──────────────────────────────────────────────────────────────────

# P12: the cent class has no demo, whatever the order of actions
no_cent_demo = Unreachable(
    Exists(some, And(some.kind == AccountKind.CENT, some.mode == Mode.DEMO)),
    max_states=BUDGET,
)
archived_account_exists = Reachable(
    Exists(some, some.status == AccountStatus.ARCHIVED), max_states=BUDGET
)

# ── scenarios ────────────────────────────────────────────────────────────────

main = accounts["main"]
_registered_client = Client(onboarding=Onboarding.CONTACTS)
# money on an account must have been deposited (payments' conservation
# invariant), and depositing needs at least the LOW tier
_funded_client = Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW, deposited=1)

sc_open_real_standard = Scenario(
    name="A registered client opens a real standard account",
    action=open_account.bind(acct=main, kind=AccountKind.STANDARD, mode=Mode.REAL),
    given=[_registered_client, Absent(main)],
    then=[Present(main), main.kind == AccountKind.STANDARD, main.balance == 0],
)

sc_unregistered_cannot_open = Scenario(
    name="An unregistered client cannot open an account",
    action=open_account.bind(acct=main, kind=AccountKind.STANDARD, mode=Mode.DEMO),
    given=[Client(), Absent(main)],
    expected=Expect.FAIL,
)

sc_archive_idle_account = Scenario(
    name="An idle real account is archived",
    action=archive.bind(acct=main),
    given=[_registered_client, main()],
    then=[main.status == AccountStatus.ARCHIVED],
)

sc_archive_with_open_position_is_rejected = Scenario(
    name="An account with an open position is not archived",
    action=archive.bind(acct=main),
    given=[_funded_client, main(balance=1, position=True)],
    expected=Expect.FAIL,
)

sc_restore_archived = Scenario(
    name="The client restores an archived account",
    action=restore.bind(acct=main),
    given=[_registered_client, main(status=AccountStatus.ARCHIVED)],
    then=[main.status == AccountStatus.ACTIVE],
)

sc_disable_by_compliance = Scenario(
    name="Compliance disables a real account even with an open position",
    action=disable.bind(acct=main),
    given=[_funded_client, main(balance=1, position=True)],
    then=[main.status == AccountStatus.DISABLED],
)

sc_support_reactivates = Scenario(
    name="Support reactivates a disabled account",
    action=support_reactivates.bind(acct=main),
    given=[_registered_client, main(status=AccountStatus.DISABLED)],
    then=[main.status == AccountStatus.ACTIVE],
)

sc_delete_inactive_demo = Scenario(
    name="An inactive demo account is deleted",
    action=delete_inactive_demo.bind(acct=main),
    given=[_registered_client, main(mode=Mode.DEMO)],
    then=[Not(Present(main))],
)

sc_demo_trades_without_money = Scenario(
    name="A demo account trades without a deposit",
    action=open_position.bind(acct=main),
    given=[_registered_client, main(mode=Mode.DEMO)],
    then=[main.position],
)

sc_archived_account_cannot_trade = Scenario(
    name="An archived account cannot open a position",
    action=open_position.bind(acct=main),
    given=[_funded_client, main(status=AccountStatus.ARCHIVED, balance=1)],
    expected=Expect.FAIL,
)

sc_gated_region_needs_full_verification_to_trade = Scenario(
    name="In a trading-gated region a real position needs full verification",
    action=open_position.bind(acct=main),
    given=[
        Client(
            onboarding=Onboarding.DETAILS,
            tier=Tier.LOW,
            deposited=1,
            region=Region.TRADING_GATED,
        ),
        main(balance=1),
    ],
    expected=Expect.FAIL,
)

sc_close_position = Scenario(
    name="A position is closed",
    action=close_position.bind(acct=main),
    given=[_funded_client, main(balance=1, position=True)],
    then=[Not(main.position)],
)

sc_disabled_account_cannot_close = Scenario(
    name="A disabled account cannot trade, not even to close",
    action=close_position.bind(acct=main),
    given=[_funded_client, main(status=AccountStatus.DISABLED, balance=1, position=True)],
    expected=Expect.FAIL,
)

trading_accounts = Contract(
    id="trading_accounts",
    name="Trading accounts and positions",
    entities=[Client, Account],
    scopes=[accounts],
    actions=[
        open_account,
        archive,
        restore,
        disable,
        support_reactivates,
        delete_inactive_demo,
        open_position,
        close_position,
    ],
    queries=[no_cent_demo, archived_account_exists],
    scenarios=[
        sc_open_real_standard,
        sc_unregistered_cannot_open,
        sc_archive_idle_account,
        sc_archive_with_open_position_is_rejected,
        sc_restore_archived,
        sc_disable_by_compliance,
        sc_support_reactivates,
        sc_delete_inactive_demo,
        sc_demo_trades_without_money,
        sc_archived_account_cannot_trade,
        sc_gated_region_needs_full_verification_to_trade,
        sc_close_position,
        sc_disabled_account_cannot_close,
    ],
)
