"""Increment M1 — the client profile: registration, KYC and security codes.

Verification is sequential: confirm contacts, fill personal details, complete
the economic profile, then an identity document and an address document. Each
document is reviewed; a rejected document may be resubmitted, but after
DOC_ATTEMPTS failed reviews it locks and only support can reopen it. Each
completed level raises the deposit tier (`Client.tier`), which payments read.
"""

from analint import (
    Action,
    Add,
    And,
    Assert,
    Contract,
    Expect,
    Flow,
    Implies,
    Invariant,
    NoDeadEnd,
    Not,
    Or,
    Reachable,
    Scenario,
    Set,
)

from .domain import BUDGET, DOC_ATTEMPTS, Client, ClientStatus, DocStatus, Onboarding, Tier

LAST_ATTEMPT = DOC_ATTEMPTS - 1

# ── registration ─────────────────────────────────────────────────────────────

confirm_contacts = Action(
    name="Confirm email and phone",
    pre=[Client.onboarding == Onboarding.NEW],
    effect=[Set(Client.onboarding, Onboarding.CONTACTS)],
)

fill_details = Action(
    name="Fill in personal details",
    pre=[Client.onboarding == Onboarding.CONTACTS],
    effect=[Set(Client.onboarding, Onboarding.DETAILS), Set(Client.tier, Tier.LOW)],
)

complete_profile = Action(
    name="Complete the economic profile",
    pre=[Client.onboarding == Onboarding.DETAILS],
    effect=[Set(Client.onboarding, Onboarding.PROFILE)],
)

# ── identity document ────────────────────────────────────────────────────────

submit_identity = Action(
    name="Upload an identity document",
    pre=[
        Client.onboarding == Onboarding.PROFILE,
        Or(Client.identity_doc == DocStatus.MISSING, Client.identity_doc == DocStatus.REJECTED),
    ],
    effect=[Set(Client.identity_doc, DocStatus.PENDING)],
)

approve_identity = Action(
    name="Reviewer approves the identity document",
    pre=[Client.identity_doc == DocStatus.PENDING],
    effect=[Set(Client.identity_doc, DocStatus.APPROVED), Set(Client.tier, Tier.HIGHER)],
)

reject_identity = Action(
    name="Reviewer rejects the identity document (may resubmit)",
    pre=[Client.identity_doc == DocStatus.PENDING, Client.identity_failures < LAST_ATTEMPT],
    effect=[Set(Client.identity_doc, DocStatus.REJECTED), Add(Client.identity_failures, 1)],
)

lock_identity = Action(
    name="Reviewer rejects the identity document for the last time",
    pre=[Client.identity_doc == DocStatus.PENDING, Client.identity_failures == LAST_ATTEMPT],
    effect=[Set(Client.identity_doc, DocStatus.LOCKED)],
)

support_reopens_identity = Action(
    name="Support reopens a locked identity document",
    pre=[Client.identity_doc == DocStatus.LOCKED],
    effect=[Set(Client.identity_doc, DocStatus.MISSING), Set(Client.identity_failures, 0)],
)

# ── address document (only after the identity document is approved) ──────────

submit_address = Action(
    name="Upload a proof of address",
    pre=[
        Client.identity_doc == DocStatus.APPROVED,
        Or(Client.address_doc == DocStatus.MISSING, Client.address_doc == DocStatus.REJECTED),
    ],
    effect=[Set(Client.address_doc, DocStatus.PENDING)],
)

approve_address = Action(
    name="Reviewer approves the proof of address",
    pre=[Client.address_doc == DocStatus.PENDING],
    effect=[Set(Client.address_doc, DocStatus.APPROVED), Set(Client.tier, Tier.FULL)],
)

reject_address = Action(
    name="Reviewer rejects the proof of address (may resubmit)",
    pre=[Client.address_doc == DocStatus.PENDING, Client.address_failures < LAST_ATTEMPT],
    effect=[Set(Client.address_doc, DocStatus.REJECTED), Add(Client.address_failures, 1)],
)

lock_address = Action(
    name="Reviewer rejects the proof of address for the last time",
    pre=[Client.address_doc == DocStatus.PENDING, Client.address_failures == LAST_ATTEMPT],
    effect=[Set(Client.address_doc, DocStatus.LOCKED)],
)

support_reopens_address = Action(
    name="Support reopens a locked proof of address",
    pre=[Client.address_doc == DocStatus.LOCKED],
    effect=[Set(Client.address_doc, DocStatus.MISSING), Set(Client.address_failures, 0)],
)

# ── security codes ───────────────────────────────────────────────────────────

request_code = Action(
    name="Client receives a one-time security code",
    pre=[Not(Client.code_confirmed)],
    effect=[Set(Client.code_confirmed, True)],
)

code_expires = Action(
    name="An unused security code expires",
    pre=[Client.code_confirmed],
    effect=[Set(Client.code_confirmed, False)],
)

# ── invariants: the stored tier never disagrees with the documents ───────────

full_tier_means_both_documents = Invariant(
    Implies(
        Client.tier == Tier.FULL,
        And(Client.identity_doc == DocStatus.APPROVED, Client.address_doc == DocStatus.APPROVED),
    ),
    label="FULL tier ⇒ both documents approved",
)

both_documents_mean_full_tier = Invariant(
    Implies(
        And(Client.identity_doc == DocStatus.APPROVED, Client.address_doc == DocStatus.APPROVED),
        Client.tier == Tier.FULL,
    ),
    label="both documents approved ⇒ FULL tier",
)

address_needs_identity = Invariant(
    Implies(Client.address_doc != DocStatus.MISSING, Client.identity_doc == DocStatus.APPROVED),
    label="a proof of address exists only after the identity document is approved",
)

documents_need_a_profile = Invariant(
    Implies(Client.identity_doc != DocStatus.MISSING, Client.onboarding == Onboarding.PROFILE),
    label="documents are uploaded only after the economic profile",
)

# ── queries ──────────────────────────────────────────────────────────────────

verification_can_complete = Reachable(Client.tier == Tier.FULL, max_states=BUDGET)
final_rejection_can_happen = Reachable(Client.identity_doc == DocStatus.LOCKED, max_states=BUDGET)
# P7: a lock is never a dead end — support reopens it. Termination (a later
# increment) is the one deliberate way out of verification.
verification_never_stuck = NoDeadEnd(
    Or(Client.tier == Tier.FULL, Client.status == ClientStatus.TERMINATED), max_states=BUDGET
)

# ── scenarios ────────────────────────────────────────────────────────────────

sc_details_raise_the_tier = Scenario(
    name="Filling in personal details unlocks the LOW deposit tier",
    action=fill_details,
    given=[Client(onboarding=Onboarding.CONTACTS)],
    then=[Client.tier == Tier.LOW],
)

sc_identity_before_profile_is_rejected = Scenario(
    name="An identity document cannot be uploaded before the economic profile",
    action=submit_identity,
    given=[Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW)],
    expected=Expect.FAIL,
)

sc_last_failure_locks_the_document = Scenario(
    name="The last failed review locks the document",
    action=lock_identity,
    given=[
        Client(
            onboarding=Onboarding.PROFILE,
            tier=Tier.LOW,
            identity_doc=DocStatus.PENDING,
            identity_failures=LAST_ATTEMPT,
        )
    ],
    then=[Client.identity_doc == DocStatus.LOCKED],
)

sc_locked_document_cannot_be_resubmitted = Scenario(
    name="A locked document cannot be resubmitted without support",
    action=submit_identity,
    given=[
        Client(
            onboarding=Onboarding.PROFILE,
            tier=Tier.LOW,
            identity_doc=DocStatus.LOCKED,
            identity_failures=LAST_ATTEMPT,
        )
    ],
    expected=Expect.FAIL,
)

sc_address_before_identity_is_rejected = Scenario(
    name="A proof of address needs an approved identity document",
    action=submit_address,
    given=[Client(onboarding=Onboarding.PROFILE, tier=Tier.LOW, identity_doc=DocStatus.PENDING)],
    expected=Expect.FAIL,
)

sc_contacts_start_onboarding = Scenario(
    name="Confirming contacts starts onboarding",
    action=confirm_contacts,
    given=[Client()],
    then=[Client.onboarding == Onboarding.CONTACTS, Client.tier == Tier.NONE],
)

sc_profile_after_details = Scenario(
    name="The economic profile follows the personal details",
    action=complete_profile,
    given=[Client(onboarding=Onboarding.DETAILS, tier=Tier.LOW)],
    then=[Client.onboarding == Onboarding.PROFILE],
)

_reviewing_identity = Client(
    onboarding=Onboarding.PROFILE, tier=Tier.LOW, identity_doc=DocStatus.PENDING
)

sc_identity_approval_raises_the_tier = Scenario(
    name="An approved identity document unlocks the HIGHER tier",
    action=approve_identity,
    given=[_reviewing_identity],
    then=[Client.tier == Tier.HIGHER],
)

sc_first_identity_failure_allows_resubmission = Scenario(
    name="A first failed review allows resubmission",
    action=reject_identity,
    given=[_reviewing_identity],
    then=[Client.identity_doc == DocStatus.REJECTED, Client.identity_failures == 1],
)

sc_support_reopens_a_locked_identity = Scenario(
    name="Support reopens a locked identity document and resets the attempts",
    action=support_reopens_identity,
    given=[
        Client(
            onboarding=Onboarding.PROFILE,
            tier=Tier.LOW,
            identity_doc=DocStatus.LOCKED,
            identity_failures=LAST_ATTEMPT,
        )
    ],
    then=[Client.identity_doc == DocStatus.MISSING, Client.identity_failures == 0],
)

_reviewing_address = Client(
    onboarding=Onboarding.PROFILE,
    tier=Tier.HIGHER,
    identity_doc=DocStatus.APPROVED,
    address_doc=DocStatus.PENDING,
)

sc_address_approval_completes_verification = Scenario(
    name="An approved proof of address completes verification",
    action=approve_address,
    given=[_reviewing_address],
    then=[Client.tier == Tier.FULL],
)

sc_first_address_failure_allows_resubmission = Scenario(
    name="A first failed address review allows resubmission",
    action=reject_address,
    given=[_reviewing_address],
    then=[Client.address_doc == DocStatus.REJECTED],
)

sc_last_address_failure_locks_it = Scenario(
    name="The last failed address review locks it",
    action=lock_address,
    given=[
        Client(
            onboarding=Onboarding.PROFILE,
            tier=Tier.HIGHER,
            identity_doc=DocStatus.APPROVED,
            address_doc=DocStatus.PENDING,
            address_failures=LAST_ATTEMPT,
        )
    ],
    then=[Client.address_doc == DocStatus.LOCKED],
)

sc_support_reopens_a_locked_address = Scenario(
    name="Support reopens a locked proof of address",
    action=support_reopens_address,
    given=[
        Client(
            onboarding=Onboarding.PROFILE,
            tier=Tier.HIGHER,
            identity_doc=DocStatus.APPROVED,
            address_doc=DocStatus.LOCKED,
            address_failures=LAST_ATTEMPT,
        )
    ],
    then=[Client.address_doc == DocStatus.MISSING, Client.address_failures == 0],
)

sc_code_is_issued = Scenario(
    name="A security code is issued",
    action=request_code,
    given=[Client()],
    then=[Client.code_confirmed],
)

sc_code_expires = Scenario(
    name="An unused security code expires",
    action=code_expires,
    given=[Client(code_confirmed=True)],
    then=[Not(Client.code_confirmed)],
)

# A new client becomes fully verified, surviving one rejected identity document.
flow_onboarding = Flow(
    given=[Client()],
    steps=[
        confirm_contacts,
        fill_details,
        complete_profile,
        submit_identity,
        reject_identity,
        submit_identity,
        approve_identity,
        Assert(Client.tier == Tier.HIGHER),
        submit_address,
        approve_address,
        Assert(Client.tier == Tier.FULL),
    ],
)

profile = Contract(
    id="profile",
    name="Client profile, verification and security codes",
    actions=[
        confirm_contacts,
        fill_details,
        complete_profile,
        submit_identity,
        approve_identity,
        reject_identity,
        lock_identity,
        support_reopens_identity,
        submit_address,
        approve_address,
        reject_address,
        lock_address,
        support_reopens_address,
        request_code,
        code_expires,
    ],
    invariants=[
        full_tier_means_both_documents,
        both_documents_mean_full_tier,
        address_needs_identity,
        documents_need_a_profile,
    ],
    queries=[verification_can_complete, final_rejection_can_happen, verification_never_stuck],
    scenarios=[
        sc_contacts_start_onboarding,
        sc_details_raise_the_tier,
        sc_profile_after_details,
        sc_identity_before_profile_is_rejected,
        sc_identity_approval_raises_the_tier,
        sc_first_identity_failure_allows_resubmission,
        sc_last_failure_locks_the_document,
        sc_locked_document_cannot_be_resubmitted,
        sc_support_reopens_a_locked_identity,
        sc_address_before_identity_is_rejected,
        sc_address_approval_completes_verification,
        sc_first_address_failure_allows_resubmission,
        sc_last_address_failure_locks_it,
        sc_support_reopens_a_locked_address,
        sc_code_is_issued,
        sc_code_expires,
    ],
    flows=[flow_onboarding],
)
