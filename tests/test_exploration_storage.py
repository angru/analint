"""Storage choices preserve reports, graph order and reachability."""

from collections import deque
from pathlib import Path

import pytest

from analint.reporter.json_reporter import result_to_dict
from analint.validator import explorer
from analint.validator.engine import validate
from analint.validator.exploration_service import explore_path


def _without_timing(value):
    if isinstance(value, dict):
        return {key: _without_timing(item) for key, item in value.items() if key != "elapsed_ms"}
    if isinstance(value, list):
        return [_without_timing(item) for item in value]
    return value


def _dict_reachable(exp, goals):
    reverse = {}
    for src, dst in zip(exp.edge_src, exp.edge_dst, strict=True):
        reverse.setdefault(dst, []).append(src)
    reached = set(goals)
    stack = list(reached)
    while stack:
        for prev in reverse.get(stack.pop(), ()):
            if prev not in reached:
                reached.add(prev)
                stack.append(prev)
    return reached


@pytest.mark.parametrize("goals", [[], [0], [2], [2, 4], [5]])
def test_compact_reverse_index(goals):
    exp = explorer.Exploration()
    for state in range(6):
        exp.add_state(bytes([state]), -1, -1)
    exp.edge_src.extend([0, 0, 0, 1, 2, 3, 4])
    exp.edge_dst.extend([0, 1, 1, 2, 1, 2, 4])
    expected = _dict_reachable(exp, goals)
    assert explorer._co_reachable(exp, goals) == bytearray(i in expected for i in range(6))


class _LiveContexts(deque):
    def push(self, idx, ctx, rejected, keys):
        self.append((idx, ctx, rejected, keys))

    def pop_state(self):
        return self.popleft()


def _legacy_reverse(exp, goals):
    reached = _dict_reachable(exp, goals)
    return bytearray(i in reached for i in range(len(exp.keys)))


@pytest.mark.parametrize(
    ("name", "checks"),
    [
        ("cloak", None),
        ("trollbridge", None),
        ("mafia", None),
        ("branch_protection", ["never_merge_underapproved", "never_merge_behind"]),
    ],
)
@pytest.mark.parametrize("sliced", [False, True])
def test_storage_matches_full_graphs(name, checks, sliced, monkeypatch):
    path = Path("examples") / name
    report = _without_timing(result_to_dict(validate(path, sliced=sliced, checks=checks)))
    artifact = explore_path(path).to_dict()

    monkeypatch.setattr(explorer, "_Frontier", _LiveContexts)
    monkeypatch.setattr(explorer, "_co_reachable", _legacy_reverse)
    monkeypatch.setattr(explorer.ExplorationStorage, "stores_edges", lambda *args: True)
    monkeypatch.setattr(explorer.Exploration, "release_graph", lambda self: None)
    assert _without_timing(result_to_dict(validate(path, sliced=sliced, checks=checks))) == report
    assert explore_path(path).to_dict() == artifact


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("reader", ["recoverability", "multi_root"])
def test_keep_edges_for_readers_and_release_finished_groups(sliced, reader, monkeypatch):
    from analint import Action, AlwaysHolds, Entity, Invariant, NoDeadEnd, Not, Reachable, Set, Spec
    from analint.validator.engine import validate_spec

    class Switch(Entity):
        on: bool = False

    turn_on = Action(id="turn_on", pre=[Not(Switch.on)], effect=[Set(Switch.on, True)])
    first = AlwaysHolds(Switch.on >= False, id="first", max_states=10)
    if reader == "recoverability":
        second = NoDeadEnd(Switch.on, id="second", max_states=20)
    else:
        second = Reachable(Switch.on, id="second", max_states=20, given_any=[[], [Switch(on=True)]])
    spec = Spec(
        id="switch",
        name="Switch",
        actions=[turn_on],
        invariants=[Invariant(Switch.on >= False, id="valid")],
        queries=[first, second],
        max_states=10,
    )
    graphs = []
    run = explorer._explore

    def observe(*args):
        budget = args[2]
        if budget == 20:
            assert not any(exp.keys for old_budget, exp, _ in graphs if old_budget == 10)
        exp = run(*args)
        graphs.append((budget, exp, len(exp.edge_src)))
        return exp

    monkeypatch.setattr(explorer, "_explore", observe)
    result = validate_spec(spec, sliced=sliced)
    assert result.verdict == "PASS"
    assert any(budget == 10 for budget, _, _ in graphs)
    assert all(edges == 0 for budget, _, edges in graphs if budget == 10)
    assert any(edges > 0 for budget, _, edges in graphs if budget == 20)
    assert all(not exp.keys for _, exp, _ in graphs)


def test_storage_planning_does_not_intern_future_roots():
    from analint import Action, And, Entity, Initial, Reachable, Set, Spec
    from analint.validator.engine import validate_spec

    class Counter(Entity):
        n: int | float = 0

    exact = 2**53
    jump = Action(id="jump", effect=[Set(Counter.n, exact)])
    exact_sum = Reachable(And(Counter.n == exact, Counter.n + 1 > Counter.n), id="exact_sum")
    approximate = Reachable(
        Counter.n == exact, id="approximate", initial=Initial(given=[Counter(n=float(exact))])
    )
    spec = Spec(id="numeric", name="Numeric", actions=[jump], queries=[exact_sum, approximate])

    result = validate_spec(spec)
    assert result.verdict == "PASS"
    assert result.query_results[0].trace == ["jump"]


@pytest.mark.parametrize("reader", ["states", "order", "parents", "edges", "trace", "reverse"])
def test_released_graph_rejects_reads(reader):
    exp = explorer.Exploration()
    exp.add_state(b"root", -1, -1)
    exp.release_graph()
    assert exp.state_count == 1
    with pytest.raises(AssertionError, match="released"):
        if reader == "trace":
            exp.trace_to(b"root")
        elif reader == "reverse":
            explorer._co_reachable(exp, [])
        else:
            len(getattr(exp, reader))


def test_edgeless_exploration_rejects_edge_reads():
    exp = explorer.explore(explorer.Spec(id="empty", name="Empty"), [{}], 10, store_edges=False)
    assert len(exp.states) == 1
    with pytest.raises(AssertionError, match="not stored"):
        len(exp.edges)
    with pytest.raises(AssertionError, match="not stored"):
        explorer._co_reachable(exp, [0])


def test_reduced_recoverability_matches_full_storage(monkeypatch):
    from analint import Action, AlwaysHolds, Entity, NoDeadEnd, Not, Set, Spec
    from analint.validator.engine import validate_spec

    class Gate(Entity):
        allowed: bool = True

    class Process(Entity):
        done: bool = False

    spec = Spec(
        id="recoverable",
        name="Recoverable",
        actions=[
            Action(id="restrict", effect=[Set(Gate.allowed, False)]),
            Action(id="restore", pre=[Not(Gate.allowed)], effect=[Set(Gate.allowed, True)]),
            Action(
                id="finish", pre=[Gate.allowed, Not(Process.done)], effect=[Set(Process.done, True)]
            ),
        ],
        queries=[
            AlwaysHolds(Process.done >= False, id="safety"),
            NoDeadEnd(Process.done, id="recover"),
        ],
    )

    report = _without_timing(result_to_dict(validate_spec(spec, sliced=True)))
    recovery = report["queries"][1]
    assert recovery["status"] == "PASS"
    assert recovery["slice"]["restorable_flags"] == 1
    assert recovery["states_explored"] == 2
    monkeypatch.setattr(explorer, "_Frontier", _LiveContexts)
    monkeypatch.setattr(explorer, "_co_reachable", _legacy_reverse)
    monkeypatch.setattr(explorer.ExplorationStorage, "stores_edges", lambda *args: True)
    monkeypatch.setattr(explorer.Exploration, "release_graph", lambda self: None)
    assert _without_timing(result_to_dict(validate_spec(spec, sliced=True))) == report
