"""``check --cache`` memoises explorations on disk. A hit must give exactly the
report a fresh run gives, a change to anything an exploration depends on
must miss, and a cache that cannot be read must only cost time."""

from __future__ import annotations

import json
import subprocess
import sys
from enum import StrEnum
from pathlib import Path

import pytest

from analint import (
    Action,
    Add,
    Entity,
    Event,
    Field,
    Invariant,
    Lifecycle,
    Scope,
    Set,
    Spec,
)
from analint.reporter.json_reporter import result_to_dict
from analint.validator import exploration_cache, explorer
from analint.validator.engine import validate
from analint.validator.exploration_cache import digest

ROOT = Path(__file__).parent.parent
MODELS = [
    *sorted(p for p in (ROOT / "examples").iterdir() if (p / "spec.py").exists()),
    ROOT / "benchmarks" / "broker" / "m6_methods.py",
]


def _report(path: Path, **kwargs) -> dict:
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k != "elapsed_ms"}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    return strip(result_to_dict(validate(path, **kwargs)))


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


@pytest.mark.parametrize("budget", [None, 30])  # 30: capped explorations too
@pytest.mark.parametrize("path", MODELS, ids=lambda p: p.stem if p.suffix else p.name)
def test_a_cached_run_reports_exactly_what_a_fresh_run_does(path, budget, cache_dir, monkeypatch):
    fresh = _report(path, max_states=budget)
    assert _report(path, max_states=budget, cache=True) == fresh  # cold: explores, stores
    calls = []
    real = explorer._explore
    monkeypatch.setattr(explorer, "_explore", lambda *a: calls.append(1) or real(*a))
    assert _report(path, max_states=budget, cache=True) == fresh  # warm: decodes
    assert calls == []


def test_capped_growth_and_excluded_actions_survive_the_cache(tmp_path, cache_dir):
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Add, Entity, Event, Field, Invariant, Reachable, Spec\n"
        "class Ping(Event):\n"
        "    n: int = 0\n"
        "class Meter(Entity):\n"
        "    n: int = 0\n"
        "class Gauge(Entity):\n"
        "    n: int = Field(0, ge=0, le=3)\n"
        "tick = Action(effect=[Add(Meter.n, 1)])\n"
        "nudge = Action(pre=[Gauge.n < 3], effect=[Add(Gauge.n, 1)])\n"
        "on_ping = Action(pre=[Ping.n > 0, Gauge.n < 3], effect=[Add(Gauge.n, 1)])\n"
        "small = Invariant(Gauge.n >= 0)\n"
        "big = Reachable(Meter.n == 99)\n"
        "spec = Spec(id='m', name='m', actions=[tick, nudge, on_ping], invariants=[small],\n"
        "            queries=[big])\n"
    )
    fresh = _report(entry, max_states=5)
    messages = json.dumps(fresh)
    # big caps on an unbounded field; small is complete but misses on_ping
    assert "Meter.n" in messages and "were excluded from exploration" in messages
    assert _report(entry, max_states=5, cache=True) == fresh
    assert _report(entry, max_states=5, cache=True) == fresh


@pytest.mark.parametrize("name", ["k8s_replicaset", "fulfillment", "cloak", "mafia"])
def test_a_cache_written_by_one_process_serves_another(name, cache_dir):
    # a fresh process interns values from scratch: codes differ, values must not
    command = [str(Path(sys.executable).parent / "analint"), "check", str(ROOT / "examples" / name)]
    command += ["--cache", "-f", "json"]

    def run() -> dict:
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        report = json.loads(done.stdout)
        for item in report["invariants"] + report["queries"]:
            item.pop("elapsed_ms", None)
        return report

    cold = run()
    assert any(cache_dir.iterdir())
    assert run() == cold


def test_an_unreadable_entry_is_a_miss(cache_dir):
    path = ROOT / "examples" / "cloak"
    fresh = _report(path, cache=True)
    for entry in cache_dir.iterdir():
        entry.write_bytes(b"not a cache entry")
    assert _report(path, cache=True) == fresh


# ── the digest covers every input of an exploration ─────────────────────────


class _S(StrEnum):
    OPEN = "open"
    DONE = "done"


class _Shipped(Event):
    count: int = 0


def _model(**change):
    """A small model; ``change`` swaps one ingredient for a variant."""

    class Box(Entity):
        n: int = Field(change.get("default", 0), ge=0, le=change.get("le", 3))
        status: _S = Lifecycle(
            _S.OPEN,
            transitions={_S.OPEN: [_S.DONE]},
            terminal=change.get("terminal", [_S.DONE]),
        )

    class Slot(Entity):
        on: bool = False

    slots = Scope(Slot, keys=change.get("keys", ["a"]))
    bump = Action(
        id="bump",
        pre=[Box.n < change.get("guard", 3)],
        effect=[Add(Box.n, change.get("step", 1))],
        post=change.get("post", []),
        emits=change.get("emits", []),
    )
    close = Action(id="close", effect=[Set(Box.status, _S.DONE)])
    spec = Spec(
        id="s",
        name="s",
        entities=[Box, Slot],
        scopes=[slots],
        actions=[bump, close],
        invariants=[
            Invariant(Box.n <= change.get("cap", 3), id="cap", label=change.get("label", ""))
        ],
    )
    root = {Box: Box(n=change.get("root", 0)), **{ref: ref() for ref in slots}}
    return spec, [root]


def _digest(**change):
    spec, roots = _model(**change)
    return digest(spec, roots, change.get("budget", 100), None, change.get("inert", frozenset()))[0]


def test_the_digest_is_stable_for_the_same_model():
    assert _digest() == _digest()


@pytest.mark.parametrize(
    "change",
    [
        {"guard": 2},
        {"step": 2},
        {"label": "renamed"},
        {"cap": 2},
        {"le": 4},
        {"default": 1},
        {"terminal": []},
        {"keys": ["a", "b"]},
        {"root": 1},
        {"budget": 99},
        {"inert": frozenset({0})},
        {"emits": [_Shipped]},
        {"emits": [_Shipped(count=1)]},
    ],
    ids=lambda c: next(iter(c)),
)
def test_any_change_an_exploration_depends_on_changes_the_digest(change):
    assert _digest(**change) != _digest()


def test_a_post_condition_changes_the_digest():
    spec, roots = _model()
    base = digest(spec, roots, 100, None, frozenset())[0]
    box = spec.entities[0]
    spec.actions[0].post.append(box.n >= 0)
    assert digest(spec, roots, 100, None, frozenset())[0] != base


def test_an_engine_change_changes_the_digest(monkeypatch):
    base = _digest()
    monkeypatch.setattr(exploration_cache, "_engine", lambda: "another engine")
    assert _digest() != base


def test_an_unsupported_value_is_explored_without_the_cache(cache_dir):
    class Bag(Entity):
        items: tuple = ()

    spec = Spec(
        id="b", name="b", entities=[Bag], actions=[Action(id="noop", pre=[Bag.items == ()])]
    )
    roots = [{Bag: Bag()}]
    with pytest.raises(exploration_cache._Uncacheable):
        digest(spec, roots, 10, None, frozenset())
    with exploration_cache.use_store(cache_dir):
        assert len(explorer.explore(spec, roots, 10).states) == 1
    assert not cache_dir.exists()
