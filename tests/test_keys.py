"""Declared identities remain values across every verification path."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path

import pytest

from analint import (
    Absent,
    Action,
    Bound,
    Count,
    Create,
    Emitted,
    Entity,
    Event,
    Exists,
    ForAll,
    In,
    InstanceRef,
    Key,
    Param,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Sum,
)
from analint.validator.engine import prepare_model, validate
from analint.validator.explorer import build_canonical_initials, explore, render_state
from analint.validator.rule_checker import compile_predicate, evaluate, resolve
from analint.validator.scenario_runner import run_scenario
from analint.validator.slicing import _operand_vars
from analint.validator.structural import _check_pred_refs, _describe, validate_structural


class Item(Entity):
    owner: str = "none"


class Identity(StrEnum):
    A = "a"
    B = "b"


@pytest.mark.parametrize("value", [None, False, 1, 2.5, "one", Identity.A])
def test_key_preserves_the_declared_value_without_reading_presence(value):
    slots = Scope(Item, keys=[value])
    ref = slots[value]
    for ctx in ({}, {ref: Absent(ref)}, {ref: ref()}):
        assert resolve(Key(ref), ctx) is value
        assert evaluate(Key(ref) == value, ctx)
        assert compile_predicate(Key(ref) == value)(ctx)
    reads = set()
    _operand_vars(Key(ref), reads)
    assert reads == set()
    assert _describe(Key(ref) == value).startswith("Key(")


@pytest.mark.parametrize("target", [Item, "a", Param("value", "a"), Param("entity", Item)])
def test_key_rejects_non_instance_inputs(target):
    with pytest.raises(TypeError, match="instance Param"):
        Key(target)


def test_key_rejects_a_reference_not_declared_by_its_scope():
    slots = Scope(Item, keys=["a"])
    for key in ("a", "undeclared"):
        with pytest.raises(TypeError, match="declared InstanceRef"):
            Key(InstanceRef(slots, key))


@pytest.mark.parametrize("value", [(1, 2), frozenset({1}), float("inf"), float("nan")])
def test_key_rejects_non_scalar_values_without_restricting_existing_scopes(value):
    slots = Scope(Item, keys=[value])
    with pytest.raises(TypeError, match="JSON scalars"):
        Key(next(iter(slots)))


def test_key_binds_parameters_and_filters_static_where():
    slots = Scope(Item, keys=["a", "b"])
    src, dst = Param("src", slots), Param("dst", slots)
    copy = Action(
        id="copy",
        params=[src, dst],
        where=[Key(src) != Key(dst)],
        effect=[Set(dst.owner, Key(src))],
    )
    spec = Spec(id="s", name="S", actions=[copy])
    assert spec.scopes == [slots]
    assert len(spec.actions) == 2
    with pytest.raises(ValueError, match="where="):
        copy.bind(src=slots["a"], dst=slots["a"])
    action = copy.bind(src=slots["a"], dst=slots["b"])
    scenario = Scenario(
        id="copy",
        name="Copy",
        action=action,
        given=[Absent(slots["a"]), slots["b"]()],
        then=[slots["b"].owner == "a"],
    )
    assert run_scenario(scenario, spec).passed
    assert not [f for f in validate_structural(spec) if f.severity == "ERROR"]


def test_nested_keys_bind_quantifiers_and_aggregates_and_keep_empty_semantics():
    slots = Scope(Item, keys=[1, 2])
    x, y = Bound("x", slots), Bound("y", slots)
    predicates = [
        ForAll(x, Exists(y, Key(x) == Key(y))),
        Count(x, In(Key(x), [1, 2])) == 2,
        Sum(x, Key(x) * 2) == 6,
        ForAll(x, Count(y, Key(y) <= Key(x)) == Key(x)),
    ]
    ctx = {ref: ref() for ref in slots}
    for pred in predicates:
        assert evaluate(pred, ctx)
        assert compile_predicate(pred)(ctx)
    empty = {ref: Absent(ref) for ref in slots}
    for pred in (ForAll(x, Key(x) == 0), Count(x, Key(x) == 1) == 0, Sum(x, Key(x)) == 0):
        assert evaluate(pred, empty)
        assert compile_predicate(pred)(empty)
    unbound = Key(x) == 1
    for evaluator in (lambda: evaluate(unbound, ctx), lambda: compile_predicate(unbound)(ctx)):
        with pytest.raises(KeyError, match="no quantifier binding"):
            evaluator()
    assert any(
        "outside a quantifier" in f.message
        for f in _check_pred_refs(unbound, [Item], [], "q", [slots])
    )
    assert any(
        "not registered" in f.message for f in _check_pred_refs(Key(slots[1]) == 1, [Item], [], "q")
    )


def test_keys_work_in_create_effects_posts_and_emitted_templates():
    class Seen(Event):
        owner: str

    slots = Scope(Item, keys=["source", "target"])
    source, target = slots["source"], slots["target"]
    spawn = Action(
        id="spawn",
        effect=[Create(target, owner=Key(source))],
        post=[target.owner == Key(source)],
        emits=[Seen(owner=Key(source))],
    )
    scenario = Scenario(
        id="spawn",
        name="Spawn",
        action=spawn,
        given=[Absent(source), Absent(target)],
        then=[Emitted(Seen)],
    )
    spec = Spec(id="s", name="S", actions=[spawn], scenarios=[scenario])
    assert not [f for f in validate_structural(spec) if f.severity == "ERROR"]
    assert run_scenario(scenario, spec).passed
    from analint.validator.kernel import step

    outcome = step(spec, spawn, {source: Absent(source), target: Absent(target)})
    assert outcome.emitted[0].owner == "source"


@pytest.mark.parametrize("position", ["effect", "create", "emit"])
def test_unbound_key_in_a_value_position_is_a_structural_error(position):
    class Seen(Event):
        owner: str

    slots = Scope(Item, keys=["a"])
    ref = slots["a"]
    value = Key(Bound("x", slots))
    kwargs = {
        "effect": {"effect": [Set(ref.owner, value)]},
        "create": {"effect": [Create(ref, owner=value)]},
        "emit": {"emits": [Seen(owner=value)]},
    }[position]
    spec = Spec(id="s", name="S", actions=[Action(id="bad", **kwargs)])
    assert any("outside a quantifier" in f.message for f in validate_structural(spec))


@pytest.fixture
def key_spec(tmp_path):
    reference = Path(__file__).resolve().parents[1] / "docs" / "dsl.md"
    blocks = re.findall(
        r'^```python title="scope-identity-spec.py"\n(.*?)^```$',
        reference.read_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    assert len(blocks) == 1
    entry = tmp_path / "spec.py"
    entry.write_text(blocks[0])
    return entry


def test_key_verdicts_traces_artifacts_and_cache_agree(key_spec, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from analint.cli import app
    from analint.reporter.json_reporter import result_to_dict
    from analint.validator import explorer
    from analint.validator.exploration_service import explore_path, trace_query

    def semantic(value):
        if isinstance(value, dict):
            return {k: semantic(v) for k, v in value.items() if k != "elapsed_ms"}
        if isinstance(value, list):
            return [semantic(v) for v in value]
        return value

    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    for sliced in (False, True):
        fresh = validate(key_spec, sliced=sliced)
        assert fresh.verdict == "PASS"
        assert fresh.query_results[0].trace == ["create"]
        assert semantic(result_to_dict(validate(key_spec, sliced=sliced, cache=True))) == semantic(
            result_to_dict(fresh)
        )
    with monkeypatch.context() as patch:
        patch.setattr(explorer, "_explore", lambda *a: pytest.fail("warm cache missed"))
        assert validate(key_spec, cache=True).verdict == "PASS"
    artifact = explore_path(key_spec).to_dict()
    assert artifact["schema"] == "analint.exploration/v1"
    assert "InstanceRef" not in json.dumps(artifact)
    assert '"a"' in json.dumps(artifact)
    trace = trace_query(key_spec, "query")
    assert trace["status"] == "PASS"
    assert len(trace["steps"]) == 1
    runner = CliRunner()
    for args in (
        ["check", str(key_spec), "--strict"],
        ["explore", str(key_spec)],
        ["trace", "query", "-p", str(key_spec)],
    ):
        response = runner.invoke(app, [*args, "-f", "json"])
        assert response.exit_code == 0, response.output
        assert json.loads(response.output)["schema"].startswith("analint.")


def test_key_tlc_matches_python(key_spec):
    from analint.backends.tla import Target, export_tla
    from analint.backends.tlc import TlcUnavailable, find_tlc, run_tlc

    spec = prepare_model(key_spec).spec
    roots, error = build_canonical_initials(spec)
    assert error is None
    export = export_tla(spec, roots, target=Target("always", spec.invariants[0].expression))
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    outcome = run_tlc(export)
    assert outcome.status == "ok", outcome.output
    assert outcome.distinct_states == len(explore(spec, roots, 100).states) == 2
    assert validate(key_spec, max_states=1, tlc=True).verdict == "PASS"


def test_key_export_refuses_unsupported_float_keys():
    from analint.backends.tla import ExportError, Target, export_tla

    floating = Scope(Item, keys=[1.5])
    bad = Spec(id="f", name="F", queries=[Reachable(Key(floating[1.5]) == 1.5, id="q")])
    roots, _ = build_canonical_initials(bad)
    with pytest.raises(ExportError, match="no TLA\\+ form"):
        export_tla(bad, roots, target=Target("always", bad.queries[0].predicate))


def test_changing_only_a_key_expression_invalidates_the_cache_digest():
    from analint.validator.exploration_cache import digest

    slots = Scope(Item, keys=["a", "b"])
    a, b = slots["a"], slots["b"]
    action = Action(id="copy", effect=[Set(b.owner, Key(a))])
    spec = Spec(id="s", name="S", actions=[action])
    roots, error = build_canonical_initials(spec)
    assert error is None
    first = digest(spec, roots, 100, None, frozenset())[0]
    action.effect = [Set(b.owner, Key(b))]
    assert digest(spec, roots, 100, None, frozenset())[0] != first


@pytest.mark.parametrize(
    ("name", "states", "edges", "state_hash", "edge_hash", "root_hash"),
    [
        (
            "oauth",
            1169,
            2256,
            "f40c0764cf4ea0dce97b2b0bfcf0d92488e839349c4c56ac590d3c22b2ca732f",
            "7414b73245eac4514501ee84f587cf79df0e1e816ebdfa027ee7a7b57b49db81",
            "64da54d1683e5d954b2af740555430a6d8dd46a6f9ada406851ec31abb2e90ac",
        ),
        (
            "k8s_replicaset",
            1792,
            13008,
            "15ad91d30a7e9c6775fa47f1ec5f4fc73bbe19f89b8af11c6726485001c21a5f",
            "c13e732c32a96d0b3df150702ec43f09ce6c58aaedc83bd7476d1941f4ef1167",
            "9e866183bf3afb23a2a61c39ce0f0a0be6338c0878004697ecbf06a67a7b3f0f",
        ),
    ],
)
def test_migrated_graph_matches_the_pre_key_model(
    name, states, edges, state_hash, edge_hash, root_hash
):
    # Captured before migration, after renaming c1/c2 -> CodeId.C1/C2 and
    # rs0/rs1 -> Owner.RS0/RS1 and removing redundant action-id parameters.
    # Every labelled state, edge and root participates, not only verdicts/counts.
    path = Path(__file__).resolve().parents[1] / "examples" / name
    spec = prepare_model(path).spec
    roots, error = build_canonical_initials(spec)
    assert error is None
    exp = explore(spec, roots, 100_000)
    assert not exp.capped
    labelled = {k: json.dumps(render_state(ctx), sort_keys=True) for k, ctx in exp.states.items()}

    def digest(items):
        return hashlib.sha256(json.dumps(sorted(items), sort_keys=True).encode()).hexdigest()

    assert (len(exp.states), len(exp.edges)) == (states, edges)
    assert digest(list(labelled.values())) == state_hash
    assert digest([(labelled[s], a, labelled[t]) for s, a, t in exp.edges]) == edge_hash
    assert digest([(labelled[k], n) for k, n in exp.roots.items()]) == root_hash
