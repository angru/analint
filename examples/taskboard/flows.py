from analint import Flow
from examples.taskboard.use_cases import (
    uc_add_comment, uc_archive_card, uc_assign_card,
    uc_create_card, uc_invite_member, uc_move_card,
)

flow_onboarding = Flow(
    id="board-onboarding",
    steps=[uc_invite_member, uc_create_card],
    description="Owner sets up a board: invite members, create first card",
)

flow_card_lifecycle = Flow(
    id="card-lifecycle-flow",
    steps=[uc_create_card, uc_assign_card, uc_move_card, uc_add_comment, uc_archive_card],
    description="Full card journey from creation to archival",
)
