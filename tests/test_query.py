import sys
from pathlib import Path
from types import ModuleType

import click
from typer.testing import CliRunner

from analint import query as q
from analint.cli import app
from analint.validator.engine import build_spec, validate

TASKBOARD = Path(__file__).parent.parent / "examples" / "taskboard"
CLOAK = Path(__file__).parent.parent / "examples" / "cloak"


def _spec(path):
    spec, _, errors = build_spec(path)
    assert spec is not None, errors
    return spec


# ── overview / describe ────────────────────────────────────────────────────────


def test_overview_lists_everything():
    overview = q.spec_overview(_spec(TASKBOARD))
    assert overview["spec"]["id"] == "taskboard"
    assert len(overview["entities"]) == 7
    assert len(overview["actions"]) == 8
    assert len(overview["scenarios"]) == 16
    assert "create_card" in overview["actions"]


def test_describe_action():
    payload = q.describe(_spec(TASKBOARD), "action", "create_card")
    assert any("Board.status" in p for p in payload["pre"])
    assert payload["effect"] == ["Board.card_count += 1"]
    assert "create-card/happy" in payload["scenarios"]


def test_describe_entity():
    payload = q.describe(_spec(TASKBOARD), "entity", "Board")
    field_names = {f["name"] for f in payload["fields"]}
    assert "card_count" in field_names
    assert "create_card" in payload["written_by"]
    assert "Board.status" in payload["lifecycles"]


def test_describe_lifecycle_reports_unreachable():
    payload = q.describe(_spec(CLOAK), "lifecycle", "Game.result")
    assert payload["terminal"] == ["Result.WON", "Result.LOST"]
    assert payload["unreachable"] == []


def test_describe_not_found_lists_known():
    payload = q.describe(_spec(TASKBOARD), "action", "nope")
    assert "error" in payload
    assert "create_card" in payload["known"]


# ── affects ───────────────────────────────────────────────────────────────────


def test_affects_field():
    payload = q.affects(_spec(TASKBOARD), "Board.card_count")
    writers = {w["action"] for w in payload["written_by"]}
    assert writers == {"create_card", "archive_card"}
    board = q.describe(_spec(TASKBOARD), "entity", "Board")
    card_count = next(field for field in board["fields"] if field["name"] == "card_count")
    assert card_count["constraints"] == {"ge": "0"}
    assert "create-card/happy" in payload["scenarios"]


def test_affects_unknown_target():
    payload = q.affects(_spec(TASKBOARD), "Nope.field")
    # unknown entity in Entity.field form → empty cross-reference, not an error
    assert payload["written_by"] == []
    payload = q.affects(_spec(TASKBOARD), "nonsense")
    assert "error" in payload


# ── what-if ───────────────────────────────────────────────────────────────────


def test_what_if_patch_adds_invariant(tmp_path):
    patch = tmp_path / "hypothesis.py"
    patch.write_text(
        "from analint import Invariant\n"
        "from taskboard.entities import Board\n"
        "max_two = Invariant(Board.card_count <= 2, label='At most 2 cards')\n"
    )
    baseline = validate(TASKBOARD)
    assert baseline.failed_count == 0

    result = validate(TASKBOARD, extra=patch)
    assert result.failed_count > 0
    failed = [sr for sr in result.scenario_results if not sr.passed]
    assert any("At most 2 cards" in f.message for sr in failed for f in sr.findings)


def test_what_if_patch_on_single_file_spec(tmp_path):
    # A single-file spec (cloak: spec.py with no __init__.py) is loaded under a
    # private synthetic name; a patch reaches it through the stable `analint_spec`
    # alias. Regression for the old "No module named ..." what-if failure.
    patch = tmp_path / "hypothesis.py"
    patch.write_text(
        "from analint import Invariant\n"
        "from analint_spec import Player\n"
        "always_cloaked = Invariant(Player.has_cloak == True, label='player always cloaked')\n"
    )
    result = validate(CLOAK, extra=patch)
    assert result.load_errors == []  # the patch resolved the spec, no import error
    assert any(
        "player always cloaked" in ir.label and ir.status.value == "FAIL"
        for ir in result.invariant_results
    )


def test_what_if_alias_is_temporary_and_patch_is_reloaded(tmp_path, monkeypatch):
    patch = tmp_path / "hypothesis.py"
    sentinel = ModuleType("analint_spec")
    monkeypatch.setitem(sys.modules, "analint_spec", sentinel)

    patch.write_text(
        "from analint import Invariant\n"
        "from analint_spec import Player\n"
        "probe = Invariant(Player.has_cloak == True, label='first hypothesis')\n"
    )
    first = validate(CLOAK, extra=patch)
    assert sys.modules["analint_spec"] is sentinel
    assert any(ir.label == "first hypothesis" for ir in first.invariant_results)

    patch.write_text(
        "from analint import Invariant\n"
        "from analint_spec import Player\n"
        "probe = Invariant(Player.has_cloak == True, label='revised hypothesis')\n"
    )
    second = validate(CLOAK, extra=patch)
    assert sys.modules["analint_spec"] is sentinel
    assert any(ir.label == "revised hypothesis" for ir in second.invariant_results)
    assert all(ir.label != "first hypothesis" for ir in second.invariant_results)


# ── CLI ───────────────────────────────────────────────────────────────────────

runner = CliRunner()


def test_cli_bare_path_routes_to_check():
    result = runner.invoke(app, [str(CLOAK)])
    assert result.exit_code == 0
    assert "11 passed" in click.unstyle(result.output)


def test_cli_version_matches_package():
    from importlib.metadata import version

    import analint

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"analint {analint.__version__}"
    # __version__ comes from installed metadata, not a hardcoded literal that drifts
    assert analint.__version__ == version("analint")


def test_cli_show_action_json():
    import json

    result = runner.invoke(app, ["show", "action", "create_card", "-p", str(TASKBOARD)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["id"] == "create_card"


def test_cli_load_error_exit_code():
    result = runner.invoke(app, ["check", "/nonexistent/place"])
    assert result.exit_code == 3


def test_overview_includes_bounded_scopes():
    from analint import Entity, Scope, Spec
    from analint.query import spec_overview

    class Account(Entity):
        balance: int = 0

    accounts = Scope(Account, keys=["alice", "bob"], id="accounts")
    payload = spec_overview(Spec(id="s", name="S", entities=[Account], scopes=[accounts]))
    assert payload["scopes"] == [
        {
            "id": "accounts",
            "entity": "Account",
            "instances": ["Account['alice']", "Account['bob']"],
        }
    ]


def test_unbuildable_spec_initial_fails_without_consumers(tmp_path):
    """Spec.initial is part of the model: an empty relation must fail the run
    even with no invariants or queries to consume it (review c893ca0, P1)."""
    (tmp_path / "spec.py").write_text(
        "from analint import Entity, Field, Initial, Spec\n\n"
        "class Box(Entity):\n"
        "    n: int = Field(0, ge=0, le=1)\n\n"
        "spec = Spec(id='s', name='S', entities=[Box],\n"
        "            initial=Initial(vary=[Box.n], where=[Box.n != Box.n]))\n"
    )
    result = validate(tmp_path)
    assert result.verdict.value == "FAIL"
    assert any("canonical initial" in f.message for f in result.exploration_findings)


def test_each_excluded_action_surfaces_its_own_finding(tmp_path):
    """Two actions excluded for the same reason share a message but differ in
    location — both must survive the cross-exploration merge (review c893ca0, P2)."""
    (tmp_path / "spec.py").write_text(
        "from analint import Action, Entity, Event, Invariant, Set, Spec\n\n"
        "class Signal(Event):\n"
        "    ok: bool\n\n"
        "class Box(Entity):\n"
        "    value: int = 0\n\n"
        "a = Action(id='a', pre=[Signal.ok == True], effect=[Set(Box.value, 1)])\n"
        "b = Action(id='b', pre=[Signal.ok == True], effect=[Set(Box.value, 2)])\n"
        "spec = Spec(id='s', name='S', entities=[Box], events=[Signal], actions=[a, b],\n"
        "            invariants=[Invariant(Box.value == 0, id='z')])\n"
    )
    result = validate(tmp_path)
    locations = {f.location for f in result.exploration_findings if "excluded" in f.message}
    assert locations == {"action:a", "action:b"}


def test_executable_flow_runs_and_failing_one_fails_the_run(tmp_path):
    """A flow with given is executed through the kernel; a failed checkpoint
    fails the overall run."""
    (tmp_path / "spec.py").write_text(
        "from analint import Action, Add, Assert, Entity, Field, Flow, Spec\n\n"
        "class Counter(Entity):\n"
        "    n: int = Field(0, ge=0, le=5)\n\n"
        "bump = Action(id='bump', pre=[Counter.n < 5], effect=[Add(Counter.n, 1)])\n"
        "good = Flow(id='good', given=[Counter(n=0)], steps=[bump, Assert(Counter.n == 1)])\n"
        "bad = Flow(id='bad', given=[Counter(n=0)], steps=[bump, Assert(Counter.n == 2)])\n"
        "spec = Spec(id='s', name='S', entities=[Counter], actions=[bump], flows=[good, bad])\n"
    )
    result = validate(tmp_path)
    by_id = {fr.flow_id: fr for fr in result.flow_results}
    assert by_id["good"].passed
    assert not by_id["bad"].passed
    assert result.verdict.value == "FAIL"
