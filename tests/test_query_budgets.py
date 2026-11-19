"""A query inherits per invocation; the declaration is safe to reuse across Specs."""

import json

import pytest
from typer.testing import CliRunner

from analint import (
    Action,
    AlwaysHolds,
    DeadActions,
    Entity,
    Field,
    NoDeadEnd,
    Reachable,
    Set,
    Spec,
    Unreachable,
)
from analint.cli import app
from analint.models.query import query_budget
from analint.query import _describe_query
from analint.validator.engine import validate_spec


class Counter(Entity):
    n: int = Field(0, ge=0, le=4)


@pytest.mark.parametrize(
    "query_type", [AlwaysHolds, Unreachable, Reachable, NoDeadEnd, DeadActions]
)
@pytest.mark.parametrize("own", [False, True])
@pytest.mark.parametrize("sliced", [False, True])
def test_inherited_budget_reuse_selection_and_explicit_override(query_type, own, sliced):
    args = (
        []
        if query_type is DeadActions
        else [
            Counter.n >= 0
            if query_type is AlwaysHolds
            else Counter.n > 4
            if query_type is Unreachable
            else Counter.n == 4
        ]
    )
    query = query_type(*args, id="target", given=[Counter()] if own else [])
    bump = Action(id="bump", pre=[Counter.n < 4], effect=[Set(Counter.n, Counter.n + 1)])
    small = Spec(id="small", name="Small", actions=[bump], queries=[query], max_states=2)
    large = Spec(id="large", name="Large", actions=[bump], queries=[query], max_states=20)
    assert query.max_states is None
    for selected in [None, ["target"]]:
        short = validate_spec(small, checks=selected, sliced=sliced)
        complete = validate_spec(large, checks=selected, sliced=sliced)
        assert short.query_results[0].states_explored == 2
        assert complete.query_results[0].status == "PASS"
        assert complete.query_results[0].states_explored == 5
        assert query.max_states is None
        if selected:
            assert short.selection["budgets"]["queries"]["target"] == 2
        override = validate_spec(small, checks=selected, sliced=sliced, max_states=20)
        assert override.query_results[0].status == "PASS"
    assert _describe_query(small, "target")["max_states"] == 2
    assert _describe_query(large, "target")["max_states"] == 20
    query.max_states = 2
    explicit = validate_spec(large, sliced=sliced)
    assert explicit.query_results[0].states_explored == 2
    assert query_budget(query, 20, 10) == 10


def test_cli_show_explore_trace_and_cached_check_share_budget(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text("""from analint import Action, Entity, Field, Set, Spec, Unreachable
class C(Entity):
    n: int = Field(0, ge=0, le=4)
bump = Action(pre=[C.n < 4], effect=[Set(C.n, C.n + 1)])
safe = Unreachable(C.n > 4)
spec = Spec(id="s", name="S", actions=[bump], queries=[safe], max_states=2)
""")
    runner = CliRunner()
    for cached in [False, True, True]:
        cmd = ["check", str(entry), "-f", "json", "--check", "safe"]
        if cached:
            cmd += ["--cache"]
        result = runner.invoke(app, cmd)
        assert result.exit_code == 4, result.stdout
        assert json.loads(result.stdout)["queries"][0]["status"] == "INCONCLUSIVE"
    show = runner.invoke(app, ["show", "query", "safe", "-p", str(entry)])
    assert show.exit_code == 0, show.stdout
    assert json.loads(show.stdout)["max_states"] == 2
    trace = runner.invoke(app, ["trace", "safe", "-p", str(entry), "-f", "json"])
    assert trace.exit_code == 0, trace.stdout
    assert json.loads(trace.stdout)["status"] == "INCONCLUSIVE"
    explore = runner.invoke(app, ["explore", str(entry), "--query", "safe", "-f", "json"])
    assert explore.exit_code == 0, explore.stdout
    payload = json.loads(explore.stdout)
    assert payload["completeness"]["max_states"] == 2
