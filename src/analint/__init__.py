from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from analint.models.action import Action
from analint.models.contract import Contract
from analint.models.effect import Add, Create, Delete, Effect, Set, Subtract
from analint.models.entity import Entity, Field
from analint.models.event import Event
from analint.models.flow import Assert, Emitted, Flow
from analint.models.initial import Initial
from analint.models.invariant import Invariant
from analint.models.lifecycle import Lifecycle, Transition
from analint.models.param import Param
from analint.models.predicate import (
    And,
    Implies,
    In,
    IsNotNull,
    IsNull,
    Not,
    Or,
    Predicate,
)
from analint.models.quantifier import Bound, Count, Exists, ForAll, Max, Min, Present, Sum
from analint.models.query import (
    AlwaysHolds,
    DeadActions,
    NoDeadEnd,
    Reachable,
    Unreachable,
)
from analint.models.root import Spec
from analint.models.scenario import Expect, Scenario
from analint.models.scope import Absent, InstanceRef, Scope

try:
    __version__ = _version("analint")
except PackageNotFoundError:  # running from a source tree without an installed dist
    __version__ = "0.0.0+unknown"

__all__ = [
    # state
    "Entity",
    "Field",
    "Scope",
    "InstanceRef",
    "Absent",
    "Event",
    # constraints
    "Predicate",
    "Invariant",
    "Initial",
    "Bound",
    "ForAll",
    "Exists",
    "Count",
    "Sum",
    "Min",
    "Max",
    "Present",
    "And",
    "Or",
    "Not",
    "Implies",
    "In",
    "IsNull",
    "IsNotNull",
    # transitions
    "Action",
    "Param",
    "Effect",
    "Set",
    "Subtract",
    "Add",
    "Create",
    "Delete",
    "Lifecycle",
    "Transition",
    # examples and journeys
    "Scenario",
    "Expect",
    "Assert",
    "Emitted",
    "Flow",
    # reachability queries
    "Reachable",
    "Unreachable",
    "AlwaysHolds",
    "NoDeadEnd",
    "DeadActions",
    # root
    "Contract",
    "Spec",
    "__version__",
]
