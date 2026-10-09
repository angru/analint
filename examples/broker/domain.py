"""Shared vocabulary of a generic retail broker.

A neutral composite of common industry practice — no particular provider is
described, and every number below is an illustrative modelling bound chosen to
keep domains small (research/34 §6). Money is counted in abstract units.
"""

from enum import StrEnum

from analint import Entity, Field, Lifecycle, Scope

MONEY_CAP = 3  # abstract units a client can ever deposit in this model
DOC_ATTEMPTS = 2  # failed reviews of one document before it locks
# Exploration budget: the coupled money model (KYC × account × payments) has
# ~16k reachable states, above the 10k default — declared, not hidden.
BUDGET = 50_000


class Region(StrEnum):
    STANDARD = "standard"
    DEPOSITS_GATED = "deposits_gated"  # no deposits until fully verified
    TRADING_GATED = "trading_gated"  # no real trading until fully verified


class ClientStatus(StrEnum):
    ACTIVE = "active"
    TERMINATED = "terminated"


class Onboarding(StrEnum):
    NEW = "new"
    CONTACTS = "contacts"  # email and phone confirmed
    DETAILS = "details"  # personal details filled
    PROFILE = "profile"  # economic profile completed


class DocStatus(StrEnum):
    MISSING = "missing"
    PENDING = "pending"
    REJECTED = "rejected"  # temporary: may be resubmitted
    LOCKED = "locked"  # final rejection: only support can reopen it
    APPROVED = "approved"


class Tier(StrEnum):
    """The verification level that sets the cumulative deposit limit."""

    NONE = "none"  # limit 0
    LOW = "low"  # limit 1 — contacts + details
    HIGHER = "higher"  # limit 2 — + economic profile + identity document
    FULL = "full"  # no limit beyond MONEY_CAP — + address document


class AccountKind(StrEnum):
    CENT = "cent"
    STANDARD = "standard"
    PROFESSIONAL = "professional"


class Mode(StrEnum):
    REAL = "real"
    DEMO = "demo"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"  # after inactivity or by the client; restorable
    DISABLED = "disabled"  # by compliance; reactivated through support


class Payout(StrEnum):
    NONE = "none"
    REQUESTED = "requested"  # submitted; cannot be cancelled


DOCUMENT_REVIEW = {
    DocStatus.MISSING: [DocStatus.PENDING],
    DocStatus.PENDING: [DocStatus.APPROVED, DocStatus.REJECTED, DocStatus.LOCKED],
    DocStatus.REJECTED: [DocStatus.PENDING],
    DocStatus.LOCKED: [DocStatus.MISSING],
}


class Client(Entity):
    """The client profile: one person, its verification and its money totals."""

    status: ClientStatus = Lifecycle(
        ClientStatus.ACTIVE,
        transitions={ClientStatus.ACTIVE: [ClientStatus.TERMINATED]},
        terminal=[ClientStatus.TERMINATED],  # termination is permanent
    )
    region: Region = Region.STANDARD
    onboarding: Onboarding = Lifecycle(
        Onboarding.NEW,
        transitions={
            Onboarding.NEW: [Onboarding.CONTACTS],
            Onboarding.CONTACTS: [Onboarding.DETAILS],
            Onboarding.DETAILS: [Onboarding.PROFILE],
        },
    )
    identity_doc: DocStatus = Lifecycle(DocStatus.MISSING, transitions=DOCUMENT_REVIEW)
    identity_failures: int = Field(0, ge=0, le=DOC_ATTEMPTS - 1)
    address_doc: DocStatus = Lifecycle(DocStatus.MISSING, transitions=DOCUMENT_REVIEW)
    address_failures: int = Field(0, ge=0, le=DOC_ATTEMPTS - 1)
    tier: Tier = Lifecycle(
        Tier.NONE,
        transitions={Tier.NONE: [Tier.LOW], Tier.LOW: [Tier.HIGHER], Tier.HIGHER: [Tier.FULL]},
    )
    code_confirmed: bool = False  # a fresh one-time security code
    card_ok: bool = False  # a card that may receive payouts: used to deposit, or verified
    deposited: int = Field(0, ge=0, le=MONEY_CAP)  # cumulative
    withdrawn: int = Field(0, ge=0, le=MONEY_CAP)  # cumulative, paid out


class Account(Entity):
    """A trading account. Its kind and mode are fixed when it is opened."""

    kind: AccountKind = AccountKind.STANDARD
    mode: Mode = Mode.REAL
    status: AccountStatus = Lifecycle(
        AccountStatus.ACTIVE,
        transitions={
            AccountStatus.ACTIVE: [AccountStatus.ARCHIVED, AccountStatus.DISABLED],
            AccountStatus.ARCHIVED: [AccountStatus.ACTIVE],
            AccountStatus.DISABLED: [AccountStatus.ACTIVE],
        },
    )
    balance: int = Field(0, ge=0, le=MONEY_CAP)
    position: bool = False  # an open position; ties up 1 unit of margin on a real account
    payout: Payout = Lifecycle(
        Payout.NONE,
        transitions={Payout.NONE: [Payout.REQUESTED], Payout.REQUESTED: [Payout.NONE]},
    )


accounts = Scope(Account, keys=["main"])  # one slot; multiplicity is increment M6
