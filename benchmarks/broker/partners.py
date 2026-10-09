"""M5: partner capabilities, tier changes and accrued commission withdrawals."""

from enum import StrEnum

from examples.broker.domain import Client, ClientStatus

from analint import (
    Action,
    Add,
    And,
    Contract,
    Entity,
    Expect,
    Field,
    Invariant,
    Lifecycle,
    Not,
    Or,
    Param,
    Reachable,
    Scenario,
    Set,
)

from .domain import BENCH_BUDGET


class PartnerStatus(StrEnum):
    ACTIVE = "active"
    LINK_BLOCKED = "link_blocked"
    ON_HOLD = "on_hold"
    BLOCKED = "blocked"


class PartnerLevel(StrEnum):
    BASE = "base"
    ADVANCED = "advanced"


class Partner(Entity):
    status: PartnerStatus = Lifecycle(
        PartnerStatus.ACTIVE,
        transitions={
            PartnerStatus.ACTIVE: [
                PartnerStatus.LINK_BLOCKED,
                PartnerStatus.ON_HOLD,
                PartnerStatus.BLOCKED,
            ],
            PartnerStatus.LINK_BLOCKED: [
                PartnerStatus.ACTIVE,
                PartnerStatus.ON_HOLD,
                PartnerStatus.BLOCKED,
            ],
            PartnerStatus.ON_HOLD: [
                PartnerStatus.ACTIVE,
                PartnerStatus.LINK_BLOCKED,
                PartnerStatus.BLOCKED,
            ],
        },
        terminal=[PartnerStatus.BLOCKED],
    )
    level: PartnerLevel = PartnerLevel.BASE
    meets_requirements: bool = False


class Referral(Entity):
    attributed: bool = False


class RewardWallet(Entity):
    earned: int = Field(0, ge=0, le=2)
    accrued: int = Field(0, ge=0, le=2)
    paid: int = Field(0, ge=0, le=2)


status = Param("status", PartnerStatus)
qualified = Param("qualified", bool)
amount = Param("amount", ge=1, le=2)
active_client = Client.status == ClientStatus.ACTIVE
can_attribute = Or(Partner.status == PartnerStatus.ACTIVE, Partner.status == PartnerStatus.ON_HOLD)
can_reward = Or(
    Partner.status == PartnerStatus.ACTIVE, Partner.status == PartnerStatus.LINK_BLOCKED
)

change_partner_status = Action(
    params=[status],
    pre=[
        active_client,
        Client.code_confirmed,
        Partner.status != PartnerStatus.BLOCKED,
        Partner.status != status,
    ],
    effect=[Set(Partner.status, status), Set(Client.code_confirmed, False)],
)
set_partner_qualification = Action(
    params=[qualified],
    pre=[Partner.status != PartnerStatus.BLOCKED, Partner.meets_requirements != qualified],
    effect=[Set(Partner.meets_requirements, qualified)],
)
promote_partner = Action(
    pre=[
        Partner.status == PartnerStatus.ACTIVE,
        Partner.meets_requirements,
        Partner.level == PartnerLevel.BASE,
    ],
    effect=[Set(Partner.level, PartnerLevel.ADVANCED)],
)
automatically_downgrade_partner = Action(
    pre=[
        Partner.status != PartnerStatus.BLOCKED,
        Not(Partner.meets_requirements),
        Partner.level == PartnerLevel.ADVANCED,
    ],
    effect=[Set(Partner.level, PartnerLevel.BASE)],
)
attribute_referral = Action(
    pre=[can_attribute, Not(Referral.attributed)],
    effect=[Set(Referral.attributed, True)],
)
accrue_commission = Action(
    params=[amount],
    pre=[
        can_reward,
        Referral.attributed,
        RewardWallet.earned == 0,
        Or(
            And(Partner.level == PartnerLevel.BASE, amount == 1),
            And(Partner.level == PartnerLevel.ADVANCED, amount == 2),
        ),
    ],
    effect=[Add(RewardWallet.earned, amount), Add(RewardWallet.accrued, amount)],
)
withdraw_accrued_rewards = Action(
    pre=[
        active_client,
        Client.code_confirmed,
        Partner.status != PartnerStatus.ON_HOLD,
        RewardWallet.accrued > 0,
    ],
    effect=[
        Add(RewardWallet.paid, RewardWallet.accrued),
        Set(RewardWallet.accrued, 0),
        Set(Client.code_confirmed, False),
    ],
)  # Wallet is separate: Partner's terminal lock must not freeze accrued funds.

rewards_are_conserved = Invariant(RewardWallet.earned == RewardWallet.accrued + RewardWallet.paid)
blocked_partner_can_withdraw_accrual = Reachable(
    And(Partner.status == PartnerStatus.BLOCKED, RewardWallet.paid > 0),
    max_states=BENCH_BUDGET,
)

sc_partner_change_spends_code = Scenario(
    action=change_partner_status.bind(status=PartnerStatus.LINK_BLOCKED),
    given=[Client(code_confirmed=True), Partner()],
    then=[Partner.status == PartnerStatus.LINK_BLOCKED, Not(Client.code_confirmed)],
)
sc_partner_change_without_code_is_rejected = Scenario(
    action=change_partner_status.bind(status=PartnerStatus.ON_HOLD),
    given=[Client(), Partner()],
    expected=Expect.FAIL,
)
sc_blocked_partner_cannot_reactivate = Scenario(
    action=change_partner_status.bind(status=PartnerStatus.ACTIVE),
    given=[Client(code_confirmed=True), Partner(status=PartnerStatus.BLOCKED)],
    expected=Expect.FAIL,
)
sc_blocked_partner_cannot_attribute = Scenario(
    action=attribute_referral,
    given=[Partner(status=PartnerStatus.BLOCKED), Referral()],
    expected=Expect.FAIL,
)
sc_link_blocked_partner_cannot_attribute = Scenario(
    action=attribute_referral,
    given=[Partner(status=PartnerStatus.LINK_BLOCKED), Referral()],
    expected=Expect.FAIL,
)
sc_on_hold_partner_can_attribute = Scenario(
    action=attribute_referral,
    given=[Partner(status=PartnerStatus.ON_HOLD), Referral()],
    then=[Referral.attributed],
)
sc_on_hold_partner_cannot_earn = Scenario(
    action=accrue_commission.bind(amount=1),
    given=[Partner(status=PartnerStatus.ON_HOLD), Referral(attributed=True), RewardWallet()],
    expected=Expect.FAIL,
)
sc_blocked_partner_cannot_earn = Scenario(
    action=accrue_commission.bind(amount=1),
    given=[Partner(status=PartnerStatus.BLOCKED), Referral(attributed=True), RewardWallet()],
    expected=Expect.FAIL,
)
sc_link_blocked_partner_can_earn = Scenario(
    action=accrue_commission.bind(amount=1),
    given=[Partner(status=PartnerStatus.LINK_BLOCKED), Referral(attributed=True), RewardWallet()],
    then=[RewardWallet.earned == 1, RewardWallet.accrued == 1],
)
sc_blocked_partner_withdraws_accrued_funds = Scenario(
    action=withdraw_accrued_rewards,
    given=[
        Client(code_confirmed=True),
        Partner(status=PartnerStatus.BLOCKED),
        RewardWallet(earned=2, accrued=2),
    ],
    then=[RewardWallet.paid == 2, RewardWallet.accrued == 0, Not(Client.code_confirmed)],
)
sc_on_hold_partner_cannot_withdraw = Scenario(
    action=withdraw_accrued_rewards,
    given=[
        Client(code_confirmed=True),
        Partner(status=PartnerStatus.ON_HOLD),
        RewardWallet(earned=1, accrued=1),
    ],
    expected=Expect.FAIL,
)
sc_qualification_changes = Scenario(
    action=set_partner_qualification.bind(qualified=True),
    given=[Partner()],
    then=[Partner.meets_requirements],
)
sc_qualified_partner_is_promoted = Scenario(
    action=promote_partner,
    given=[Partner(meets_requirements=True)],
    then=[Partner.level == PartnerLevel.ADVANCED],
)
sc_unqualified_partner_is_downgraded = Scenario(
    action=automatically_downgrade_partner,
    given=[Partner(level=PartnerLevel.ADVANCED)],
    then=[Partner.level == PartnerLevel.BASE],
)

partners = Contract(
    id="partners",
    name="Partner capability matrix and accrued rewards",
    entities=[Client, Partner, Referral, RewardWallet],
    actions=[
        change_partner_status,
        set_partner_qualification,
        promote_partner,
        automatically_downgrade_partner,
        attribute_referral,
        accrue_commission,
        withdraw_accrued_rewards,
    ],
    invariants=[rewards_are_conserved],
    queries=[blocked_partner_can_withdraw_accrual],
    scenarios=[
        sc_partner_change_spends_code,
        sc_partner_change_without_code_is_rejected,
        sc_blocked_partner_cannot_reactivate,
        sc_blocked_partner_cannot_attribute,
        sc_link_blocked_partner_cannot_attribute,
        sc_on_hold_partner_can_attribute,
        sc_on_hold_partner_cannot_earn,
        sc_blocked_partner_cannot_earn,
        sc_link_blocked_partner_can_earn,
        sc_blocked_partner_withdraws_accrued_funds,
        sc_on_hold_partner_cannot_withdraw,
        sc_qualification_changes,
        sc_qualified_partner_is_promoted,
        sc_unqualified_partner_is_downgraded,
    ],
)
