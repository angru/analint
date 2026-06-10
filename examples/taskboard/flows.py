from analint import Flow
from .actions import (
    add_comment, archive_card, assign_card,
    create_card, invite_member, move_card,
)

flow_onboarding = Flow(
    id="board-onboarding",
    steps=[invite_member, create_card],
    description="Owner sets up a board: invite members, create first card",
)

flow_card_lifecycle = Flow(
    id="card-lifecycle-flow",
    steps=[create_card, assign_card, move_card, add_comment, archive_card],
    description="Full card journey from creation to archival",
)
