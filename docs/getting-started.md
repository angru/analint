# Your first spec

This example models one support ticket and a queue counter. Resolving the ticket
must decrement the counter; only a resolved ticket can be archived. The finite
model has three reachable states.

## Install and declare the model

Use Python 3.12 or newer:

```bash
pip install analint
mkdir ticket_spec
cd ticket_spec
```

Save the complete program below as `spec.py`. The documentation checks execute
this exact block, including the defect exercise later on this page.

```python title="spec.py"
from enum import StrEnum

from analint import (
    Action, Assert, Entity, Expect, Field, Flow, Implies, Invariant,
    Lifecycle, NoDeadEnd, Reachable, Scenario, Set, Spec, Subtract,
)


class Status(StrEnum):
    NEW = "new"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class Ticket(Entity):
    status: Status = Lifecycle(
        initial=Status.NEW,
        transitions={
            Status.NEW: [Status.RESOLVED],
            Status.RESOLVED: [Status.ARCHIVED],
        },
        terminal=[Status.ARCHIVED],
    )


class Queue(Entity):
    open_tickets: int = Field(1, ge=0, le=1)


resolved_leaves_no_open_ticket = Invariant(
    Implies(Ticket.status != Status.NEW, Queue.open_tickets == 0),
    label="Resolving the only ticket clears the queue counter",
)

resolve = Action(
    pre=[Ticket.status == Status.NEW],
    effect=[
        Set(Ticket.status, Status.RESOLVED),
        Subtract(Queue.open_tickets, 1),
    ],
)

archive = Action(
    pre=[Ticket.status == Status.RESOLVED],
    effect=[Set(Ticket.status, Status.ARCHIVED)],
)

resolve_new = Scenario(
    action=resolve,
    given=[Ticket(), Queue()],
    then=[Ticket.status == Status.RESOLVED, Queue.open_tickets == 0],
)

cannot_archive_new = Scenario(
    action=archive,
    given=[Ticket(), Queue()],
    expected=Expect.FAIL,
)

ticket_journey = Flow(
    given=[Ticket(), Queue()],
    steps=[
        resolve,
        Assert(Queue.open_tickets == 0),
        archive,
        Assert(Ticket.status == Status.ARCHIVED),
    ],
)

can_archive = Reachable(Ticket.status == Status.ARCHIVED)
archive_stays_possible = NoDeadEnd(goal=Ticket.status == Status.ARCHIVED)

spec = Spec(
    id="tickets",
    name="Ticket workflow",
    actions=[resolve, archive],
    invariants=[resolved_leaves_no_open_ticket],
    scenarios=[resolve_new, cannot_archive_new],
    flows=[ticket_journey],
    queries=[can_archive, archive_stays_possible],
)
```

The model contains the behaviour explicitly listed on `Spec`. Its entity types
and inline lifecycle are derived from those references. Variable names supply
ids such as `resolve` and `can_archive`; defining another action without listing
it does not add it to the model.

## Run and interpret the checks

```bash
analint check .
analint check . --format json
```

Both scenarios, the flow, the invariant and both queries pass. The overall JSON
has `schema: "analint.check/v1"`, `verdict: "PASS"` and `passed: true`; the command
exits with code `0`.

`cannot_archive_new` passes because the archive precondition rejects a new ticket
before execution. `Expect.FAIL` checks an intended rejection; it does not excuse
a broken effect, postcondition or assertion.

The scenario and flow start from their own `given` snapshots. Reachability and
automatic invariant verification use the canonical model, which here starts from
the field defaults: a new ticket and one open ticket. Exploration checks every
enabled action order within that model.

## Inspect before editing

```bash
analint show -p .
analint show action resolve -p .
analint affects Queue.open_tickets -p .
analint trace can_archive -p .
```

`show` and `affects` return JSON. The trace reaches the archived state through
`resolve → archive`, showing the counter and status changes. `NoDeadEnd` says
archiving remains possible from every reachable state; it makes no scheduling
promise that a user will actually perform those actions.

## Introduce a defect

Delete this one effect from `resolve`:

```python
Subtract(Queue.open_tickets, 1),
```

Run the check again:

```bash
analint check .
analint trace resolved_leaves_no_open_ticket -p . --format json
```

The check now fails with exit code `1`. The counterexample reaches a resolved
ticket with `Queue.open_tickets` still equal to `1`. The invariant trace names
the property under its `invariant` key and shows `resolve` as the violating step.
The invariant-invalid state is retained as evidence and has no outgoing
transitions. Restore the removed effect and check that the model passes again.

## Test a proposed rule without changing the model

First make the spec a Python package so that the checker and hypothesis share
the same entity classes. From inside `ticket_spec`, create an empty
`__init__.py`, then return to its parent directory:

```bash
touch __init__.py
cd ..
```

Save this separate file as `hypothesis.py` alongside the `ticket_spec` directory:

```python title="hypothesis.py"
from analint import Invariant
from ticket_spec.spec import Queue

queue_is_always_empty = Invariant(Queue.open_tickets == 0)
```

Then check it against the restored model:

```bash
analint check ticket_spec --what-if hypothesis.py
analint trace queue_is_always_empty -p ticket_spec --what-if hypothesis.py
```

This hypothesis fails at the initial state: the new ticket is still open. The
extra module is merged for this run; `spec.py` is unchanged. Scratch files outside
the spec directory do not cause unloaded-file warnings on normal checks. Import
shared types by their package name; importing a standalone entry as a second
module can create different entity identities.

Next, read [verification concepts](concepts.md) for roots, budgets and slicing,
or the [DSL reference](dsl.md) to model multiple tickets with a `Scope`.
