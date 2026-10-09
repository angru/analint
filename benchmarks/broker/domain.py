"""Finite abstractions for broker risk, affiliation and bounded portfolios.

Risk equity is a settlement bucket, not an amount in the M3 cash ledger. Its
changes model external market/recapitalization outcomes; no currency or price
arithmetic is claimed. Two slots exist throughout the series, but M4/M5 allow
only one concurrent risk account and order. M6 raises those explicit capacities.
"""

from enum import StrEnum

from examples.broker.domain import AccountKind

from analint import Entity, Field, Lifecycle, Scope

BENCH_BUDGET = 2_000


class Equity(StrEnum):
    SMALL = "small"
    LARGE = "large"
    ZERO = "zero"
    NEGATIVE = "negative"


class Leverage(StrEnum):
    CAPPED = "capped"
    UNCAPPED = "uncapped"


class EffectiveCap(StrEnum):
    LOW = "low"
    HIGH = "high"


class Margin(StrEnum):
    HEALTHY = "healthy"
    CALL = "call"
    STOP = "stop"


class Protection(StrEnum):
    NONE = "none"
    DUE = "due"
    PAID = "paid"


class Owner(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class OrderStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    STOPPED = "stopped"


class Capacity(Entity):
    accounts: int = Field(1, ge=1, le=2)
    orders: int = Field(1, ge=1, le=2)
    methods: int = Field(1, ge=1, le=2)


class History(Entity):
    completed_trade: bool = False  # illustrative minimum-history eligibility


class Market(Entity):
    high_margin: bool = False


class RiskAccount(Entity):
    kind: AccountKind = AccountKind.STANDARD
    equity: Equity = Equity.SMALL
    leverage: Leverage = Leverage.CAPPED
    effective_cap: EffectiveCap = EffectiveCap.LOW
    margin: Margin = Margin.HEALTHY
    fully_stopped: bool = False
    protection: Protection = Lifecycle(
        Protection.NONE,
        transitions={
            Protection.NONE: [Protection.DUE],
            Protection.DUE: [Protection.PAID],
            Protection.PAID: [Protection.NONE],
        },
    )


class Order(Entity):
    owner: Owner = Owner.PRIMARY
    profit: int = Field(0, ge=-1, le=1)
    status: OrderStatus = Lifecycle(
        OrderStatus.OPEN,
        transitions={OrderStatus.OPEN: [OrderStatus.CLOSED, OrderStatus.STOPPED]},
    )  # closed slots can be reclaimed; terminal would prohibit Delete


risk_accounts = Scope(RiskAccount, keys=["primary", "secondary"])
orders = Scope(Order, keys=["first", "second"])
