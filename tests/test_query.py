from pathlib import Path

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
    assert payload["by"] == "Member"
    assert any("Board.status" in p for p in payload["pre"])
    assert payload["effect"] == ["Board.card_count += 1"]
    assert "create-card/happy" in payload["scenarios"]
    assert "move_card" in payload["required_by"]


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


def test_affects_action_shows_downstream_triggers():
    payload = q.affects(_spec(TASKBOARD), "create_card")
    assert "send_notification" in payload["triggers_downstream"]
    assert "archive_card" in payload["required_by"]


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


# ── CLI ───────────────────────────────────────────────────────────────────────

runner = CliRunner()


def test_cli_bare_path_routes_to_check():
    result = runner.invoke(app, [str(CLOAK)])
    assert result.exit_code == 0
    assert "11 passed" in click.unstyle(result.output)


def test_cli_show_action_json():
    import json

    result = runner.invoke(app, ["show", "action", "create_card", "-p", str(TASKBOARD)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["id"] == "create_card"


def test_cli_load_error_exit_code():
    result = runner.invoke(app, ["check", "/nonexistent/place"])
    assert result.exit_code == 3
