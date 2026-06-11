from analint import Actor


class Owner(Actor):
    """Board owner — can invite members, archive board."""


class Member(Actor):
    """Regular board member — can create/move/assign/comment/archive cards."""


class System(Actor):
    """Background worker — processes queued jobs triggered by domain events."""
