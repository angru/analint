from enum import Enum
from pathlib import Path

import pytest
from typer.testing import CliRunner

from analint import (
    Action,
    Add,
    BoolValue,
    Bound,
    Create,
    Entity,
    Event,
    Field,
    Lookup,
    Param,
    Scope,
    Set,
    Spec,
    Subtract,
    Sum,
)
from analint.backends.tla import ExportError, Target, export_tla
from analint.cli import app
from analint.reporter import Code, Severity
from analint.validator.engine import build_spec, validate, validate_spec
from analint.validator.explorer import build_canonical_initials
from analint.validator.rule_checker import evaluate
from analint.validator.structural import validate_structural


class Mode(Enum):
    A = "a"
    B = "b"


class C(Entity):
    n: int = Field(0, ge=0, le=5)
    flag: bool = False
    name: str = "init"
    mode: Mode = Mode.A


class WithOpt(Entity):
    opt: int | None = None
    opt_flag: bool | None = None


class Untyped(Entity):
    val = None


class Paid(Event):
    amount: int


class Recorded(Event):
    ready: bool


def test_issue_77_repro_fails_structurally():
    repro_path = Path(__file__).resolve().parents[1] / ".venv" / "issue-77-repro.py"
    assert repro_path.exists()
    result = validate(repro_path)
    assert result.verdict == "FAIL"
    assert not result.query_results

    conflict_findings = [f for f in result.structural_findings if f.code == Code.TYPE_CONFLICT]
    assert len(conflict_findings) == 4
    locations = {f.location for f in conflict_findings}
    assert locations == {
        "action:int_from_bool",
        "action:bool_from_int",
        "action:int_from_predicate",
        "action:add_false",
    }


def test_set_literal_bool_and_int_conflicts():
    bad_int = Action(id="bad_int", effect=[Set(C.n, True)])
    bad_bool = Action(id="bad_bool", effect=[Set(C.flag, 1)])
    bad_int_false = Action(id="bad_int_false", effect=[Set(C.n, False)])
    bad_bool_zero = Action(id="bad_bool_zero", effect=[Set(C.flag, 0)])

    spec = Spec(id="s", name="S", actions=[bad_int, bad_bool, bad_int_false, bad_bool_zero])
    findings = validate_structural(spec)
    conflicts = [f for f in findings if f.code == Code.TYPE_CONFLICT]
    assert len(conflicts) == 4
    assert all(f.severity is Severity.ERROR for f in conflicts)


def test_set_field_reference_conflicts():
    bool_to_int = Action(id="b2i", effect=[Set(C.n, C.flag)])
    int_to_bool = Action(id="i2b", effect=[Set(C.flag, C.n)])

    spec = Spec(id="s", name="S", actions=[bool_to_int, int_to_bool])
    findings = validate_structural(spec)
    conflicts = [f for f in findings if f.code == Code.TYPE_CONFLICT]
    assert len(conflicts) == 2
    assert "bool field 'C.flag' to Set field 'C.n'" in conflicts[0].message
    assert "int field 'C.n' to Set field 'C.flag'" in conflicts[1].message


def test_create_type_conflicts():
    scopes = Scope(C, keys=["c1"], id="c_scope")
    ref = scopes["c1"]

    bad_n = Action(id="bad_n", effect=[Create(ref, n=True)])
    bad_flag = Action(id="bad_flag", effect=[Create(ref, flag=1)])
    bad_pred = Action(id="bad_pred", effect=[Create(ref, n=BoolValue(C.n == 0))])

    spec = Spec(id="s", name="S", scopes=[scopes], actions=[bad_n, bad_flag, bad_pred])
    findings = validate_structural(spec)
    conflicts = [f for f in findings if f.code == Code.TYPE_CONFLICT]
    assert len(conflicts) == 3


def test_add_subtract_conflicts():
    add_bool = Action(id="add_bool", effect=[Add(C.n, True)])
    sub_bool = Action(id="sub_bool", effect=[Subtract(C.n, False)])
    add_bv = Action(id="add_bv", effect=[Add(C.n, BoolValue(C.flag))])
    sub_bv = Action(id="sub_bv", effect=[Subtract(C.n, BoolValue(C.flag))])
    add_bool_field = Action(id="add_bf", effect=[Add(C.n, C.flag)])
    add_on_bool = Action(id="add_on_bool", effect=[Add(C.flag, 1)])
    sub_on_bool = Action(id="sub_on_bool", effect=[Subtract(C.flag, 1)])
    add_bv_arith = Action(id="add_bva", effect=[Add(C.n, BoolValue(C.flag) + 1)])

    spec = Spec(
        id="s",
        name="S",
        actions=[
            add_bool,
            sub_bool,
            add_bv,
            sub_bv,
            add_bool_field,
            add_on_bool,
            sub_on_bool,
            add_bv_arith,
        ],
    )
    findings = validate_structural(spec)
    conflicts = [f for f in findings if f.code == Code.TYPE_CONFLICT]
    assert len(conflicts) == 8


def test_emitted_event_payload_conflicts():
    bad_paid_lit = Action(id="p1", emits=[Paid(amount=True)])
    bad_paid_bv = Action(id="p2", emits=[Paid(amount=BoolValue(C.flag))])
    bad_paid_field = Action(id="p3", emits=[Paid(amount=C.flag)])
    bad_rec_lit = Action(id="r1", emits=[Recorded(ready=1)])
    bad_rec_field = Action(id="r2", emits=[Recorded(ready=C.n)])

    spec = Spec(
        id="s",
        name="S",
        entities=[C],
        events=[Paid, Recorded],
        actions=[bad_paid_lit, bad_paid_bv, bad_paid_field, bad_rec_lit, bad_rec_field],
    )
    findings = validate_structural(spec)
    conflicts = [f for f in findings if f.code == Code.TYPE_CONFLICT]
    assert len(conflicts) == 5


def test_fail_closed_bool_value_cases():
    bv = BoolValue(C.flag)
    scope = Scope(C, keys=["c1"], id="c_scope")
    x = Bound("x", scope)

    to_str = Action(id="to_str", effect=[Set(C.name, bv)])
    to_enum = Action(id="to_enum", effect=[Set(C.mode, bv)])
    to_opt = Action(id="to_opt", effect=[Set(WithOpt.opt, bv)])
    in_add_expr = Action(id="in_add_expr", effect=[Set(C.n, bv + 1)])
    in_radd_expr = Action(id="in_radd_expr", effect=[Set(C.n, 1 + bv)])
    in_sum = Action(id="in_sum", effect=[Set(C.n, Sum(x, BoolValue(x.flag)))])

    spec = Spec(
        id="s",
        name="S",
        scopes=[scope],
        actions=[to_str, to_enum, to_opt, in_add_expr, in_radd_expr, in_sum],
    )
    findings = validate_structural(spec)
    conflicts = [f for f in findings if f.code == Code.TYPE_CONFLICT]
    assert len(conflicts) == 6


def test_positive_controls_are_preserved():
    lookup = Lookup(C.mode, {Mode.A: 10, Mode.B: 20})
    param = Param("amount", 1, 2)
    scopes = Scope(C, keys=["c1"], id="c_scope")
    ref = scopes["c1"]

    valid_actions = [
        Action(id="a1", effect=[Set(C.n, 1)]),
        Action(id="a2", effect=[Set(C.flag, True)]),
        Action(id="a3", effect=[Set(C.flag, BoolValue(C.n == 0))]),
        Action(id="a4", effect=[Set(C.n, C.n + 1)]),
        Action(id="a5", effect=[Set(C.n, lookup)]),
        Action(id="a6", params=[param], effect=[Set(C.n, param)]),
        Action(id="a7", effect=[Add(C.n, 1), Subtract(C.n, 1)]),
        Action(id="a8", effect=[Set(WithOpt.opt, 5), Set(WithOpt.opt, None)]),
        Action(id="a9", effect=[Set(WithOpt.opt_flag, True), Set(WithOpt.opt_flag, None)]),
        Action(
            id="a10",
            effect=[
                Set(Untyped.val, 1),
                Set(Untyped.val, True),
                Set(Untyped.val, BoolValue(C.flag)),
            ],
        ),
        Action(id="a11", effect=[Create(ref, n=2, flag=BoolValue(C.flag))]),
        Action(id="a12", emits=[Paid(amount=10), Recorded(ready=BoolValue(C.flag))]),
    ]

    spec = Spec(
        id="s",
        name="S",
        events=[Paid, Recorded],
        scopes=[scopes],
        actions=valid_actions,
    )
    findings = validate_structural(spec)
    conflicts = [f for f in findings if f.code == Code.TYPE_CONFLICT]
    assert not conflicts


def test_ordered_bool_value_comparison_boundary():
    # Native evaluation retains standard Python boolean ordering
    c_false = {C: C(flag=False)}
    c_true = {C: C(flag=True)}

    gt_pred = BoolValue(C.flag) > False
    gte_pred = BoolValue(C.flag) >= True
    lt_pred = BoolValue(C.flag) < True

    assert evaluate(gt_pred, c_true) is True
    assert evaluate(gt_pred, c_false) is False
    assert evaluate(gte_pred, c_true) is True
    assert evaluate(gte_pred, c_false) is False
    assert evaluate(lt_pred, c_false) is True
    assert evaluate(lt_pred, c_true) is False

    # TLC export refuses ordered comparisons on BoolValue
    spec = Spec(id="s", name="S", actions=[Action(id="act", effect=[Set(C.flag, True)])])
    roots, _ = build_canonical_initials(spec)
    with pytest.raises(ExportError, match="BoolValue ordered comparisons are not exported to TLC"):
        export_tla(spec, roots, target=Target("always", gt_pred))


def test_normal_check_paths_with_and_without_tlc(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Entity, Field, Reachable, Set, Spec\n"
        "class Box(Entity):\n"
        "    n: int = Field(0, ge=0, le=5)\n"
        "act = Action(id='conflict', effect=[Set(Box.n, True)])\n"
        "spec = Spec(id='s', name='S', actions=[act], queries=[Reachable(Box.n == 1, id='q')])\n"
    )

    spec, _, _ = build_spec(entry)
    assert spec is not None

    # validate_spec without and with TLC
    res_no_tlc = validate_spec(spec, tlc=False)
    assert res_no_tlc.verdict == "FAIL"
    assert any(f.code == Code.TYPE_CONFLICT for f in res_no_tlc.structural_findings)
    assert not res_no_tlc.query_results

    res_tlc = validate_spec(spec, tlc=True)
    assert res_tlc.verdict == "FAIL"
    assert any(f.code == Code.TYPE_CONFLICT for f in res_tlc.structural_findings)
    assert not res_tlc.query_results

    # CLI check without and with TLC
    runner = CliRunner()
    cli_res = runner.invoke(app, ["check", str(entry), "-f", "json"])
    assert cli_res.exit_code == 1
    assert '"code": "structural.type_conflict"' in cli_res.stdout
    assert '"verdict": "FAIL"' in cli_res.stdout

    cli_tlc_res = runner.invoke(app, ["check", str(entry), "--tlc", "-f", "json"])
    assert cli_tlc_res.exit_code == 1
    assert '"code": "structural.type_conflict"' in cli_tlc_res.stdout
    assert '"verdict": "FAIL"' in cli_tlc_res.stdout
