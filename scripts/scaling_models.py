"""Generated, parameterized model families for scaling characterization (P4.4).

Each builder returns ``(spec, expected_states)`` for a known closed-form state
count, so the harness can both measure performance and verify correctness on
small/medium cases. These are synthetic shapes, not domain models — they exist to
drive engine work with reproducible state spaces, not to teach modelling.
"""

from __future__ import annotations

from enum import StrEnum
from math import comb

from analint import (
    Action,
    Add,
    Entity,
    Field,
    Initial,
    Lifecycle,
    Param,
    Scope,
    Set,
    Spec,
    Subtract,
)


def counter_grid(n: int, bound: int) -> tuple[Spec, int]:
    """``n`` independent counters each ranging 0..bound. States: (bound+1) ** n."""

    class Counter(Entity):
        value: int = Field(0, ge=0, le=bound)

    counters = Scope(Counter, keys=[f"c{i}" for i in range(n)])
    c = Param("c", counters)
    tick = Action(id="tick", params=[c], pre=[c.value < bound], effect=[Add(c.value, 1)])
    spec = Spec(
        id="counter_grid",
        name=f"Counter grid n={n} bound={bound}",
        entities=[Counter],
        scopes=[counters],
        actions=[tick],
    )
    return spec, (bound + 1) ** n


def conserved_transfer(n: int, total: int) -> tuple[Spec, int]:
    """``n`` accounts sharing a fixed ``total`` of units, moved one at a time.
    States: distributions of ``total`` over ``n`` accounts = C(total+n-1, n-1)."""

    class Account(Entity):
        coins: int = Field(0, ge=0, le=total)

    accounts = Scope(Account, keys=[f"a{i}" for i in range(n)])
    first = accounts["a0"]
    src = Param("src", accounts)
    dst = Param("dst", accounts)
    send = Action(
        id="send",
        params=[src, dst],
        where=[src != dst],
        pre=[src.coins >= 1, dst.coins <= total - 1],
        effect=[Subtract(src.coins, 1), Add(dst.coins, 1)],
    )
    # Start with every unit in a0 (the rest at 0), so the conserved sum is `total`.
    spec = Spec(
        id="conserved_transfer",
        name=f"Conserved transfer n={n} total={total}",
        entities=[Account],
        scopes=[accounts],
        actions=[send],
        initial=Initial(
            vary=[first.coins],
            where=[first.coins == total],
            given=[accounts[f"a{i}"](coins=0) for i in range(1, n)],
        ),
    )
    return spec, comb(total + n - 1, n - 1)


class _WStatus(StrEnum):
    S0 = "s0"
    S1 = "s1"
    S2 = "s2"
    S3 = "s3"


_ADVANCE = {
    _WStatus.S0: _WStatus.S1,
    _WStatus.S1: _WStatus.S2,
    _WStatus.S2: _WStatus.S3,
}


def workflow_product(n: int) -> tuple[Spec, int]:
    """``n`` independent 4-state lifecycles advancing S0→S1→S2→S3. States: 4 ** n."""

    class Workflow(Entity):
        status: _WStatus = Lifecycle(
            initial=_WStatus.S0,
            transitions={source: [target] for source, target in _ADVANCE.items()},
            terminal=[_WStatus.S3],
        )

    workflows = Scope(Workflow, keys=[f"w{i}" for i in range(n)])
    w = Param("w", workflows)
    # One action per transition (no conditional effects): each workflow advances
    # S0→S1→S2→S3 independently, so the product is 4 ** n reachable states.
    actions = [
        Action(
            id=f"advance_{frm.name}",
            params=[w],
            pre=[w.status == frm],
            effect=[Set(w.status, to)],
        )
        for frm, to in _ADVANCE.items()
    ]
    spec = Spec(
        id="workflow_product",
        name=f"Workflow product n={n}",
        entities=[Workflow],
        scopes=[workflows],
        actions=actions,
    )
    return spec, 4**n


FAMILIES = {
    "counter_grid": counter_grid,
    "conserved_transfer": conserved_transfer,
    "workflow_product": workflow_product,
}
