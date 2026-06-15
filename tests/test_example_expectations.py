"""Example intent contracts (P4.0c, research/26).

Every directory under ``examples/`` with a ``spec.py`` must declare its intended
outcome in ``examples/expectations.toml`` and explain itself in a local
``README.md``. This test checks the human-meaningful verdict (verdict, exit code,
which ids fail, where warnings land) and keeps the exact graph/state details in
``tests/snapshots/examples.json`` (test_characterization.py).

A failure here is a real signal: either a behavioural regression, or an intended
change that must be reflected in the manifest and README with an explanation — not
blessed automatically.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import validate

EXAMPLES = Path(__file__).parent.parent / "examples"
MANIFEST_PATH = EXAMPLES / "expectations.toml"
ROOT_README = Path(__file__).parent.parent / "README.md"


def _example_names() -> list[str]:
    return sorted(p.parent.name for p in EXAMPLES.glob("*/spec.py"))


def _manifest() -> dict[str, dict]:
    return tomllib.loads(MANIFEST_PATH.read_text())


def _derive_exit_code(payload: dict) -> int:
    if payload["load_errors"] or payload["spec"]["id"] == "__empty__":
        return 3
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 4}[payload["verdict"]]


def _observed(name: str) -> dict:
    payload = result_to_dict(validate(EXAMPLES / name))

    def warn_locations(key: str) -> list[str]:
        return [f["location"] for f in payload[key] if f["severity"] == "WARNING"]

    return {
        "verdict": payload["verdict"],
        "exit_code": _derive_exit_code(payload),
        "failed_scenarios": sorted(s["id"] for s in payload["scenarios"] if not s["passed"]),
        "failed_queries": sorted(q["id"] for q in payload["queries"] if q["status"] != "PASS"),
        "failed_invariants": sorted(
            i["id"] for i in payload["invariants"] if i["status"] != "PASS"
        ),
        "failed_flows": sorted(f["id"] for f in payload["flows"] if not f["passed"]),
        "warning_locations": sorted(
            set(warn_locations("structural") + warn_locations("exploration"))
        ),
    }


def test_manifest_covers_exactly_the_examples():
    assert set(_manifest()) == set(_example_names()), (
        "examples/expectations.toml must have exactly one entry per examples/*/spec.py"
    )


def test_every_example_has_a_readme():
    missing = [name for name in _example_names() if not (EXAMPLES / name / "README.md").exists()]
    assert not missing, f"examples without a README.md: {missing}"


def test_root_readme_lists_every_example():
    text = ROOT_README.read_text()
    missing = [name for name in _example_names() if name not in text]
    assert not missing, f"root README.md does not mention examples: {missing}"


@pytest.mark.parametrize("name", _example_names())
def test_example_matches_its_declared_intent(name: str):
    expected = _manifest()[name]
    observed = _observed(name)
    for field, value in observed.items():
        assert value == expected[field], (
            f"{name}: {field} is {value!r}, manifest declares {expected[field]!r}. "
            f"Fix the regression or update examples/expectations.toml with a reason."
        )
