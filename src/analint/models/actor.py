from __future__ import annotations


class Actor:
    """Base class for actors (roles). Subclass to define a role.

    Example::

        class Customer(Actor): pass
        class Admin(Actor): pass

        uc = UseCase(..., actor=Customer)
    """
