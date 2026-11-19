"""Integer // preserves Python floor semantics, binding and fail-closed evaluation."""

import pytest

from analint import (
    Action,
    AlwaysHolds,
    Bound,
    Entity,
    Field,
    ForAll,
    Not,
    Or,
    Param,
    Scope,
    Set,
    Spec,
)
from analint.backends.tla import ExportError, Target, export_tla
from analint.backends.tlc import TlcUnavailable, find_tlc
from analint.models.expr import _FloorDivExpr
from analint.models.param import _resolve
from analint.validator.engine import validate_spec
from analint.validator.explorer import build_canonical_initials
from analint.validator.rule_checker import compile_predicate, evaluate, resolve


@pytest.mark.parametrize("left", [-7, -1, 0, 1, 7])
@pytest.mark.parametrize("right", [-3, -2, 1, 2, 3])
def test_floor_matches_python_for_all_signs(left, right):
    class N(Entity):
        n: int = left

    expr = N.n // right
    ctx = {N: N()}
    assert resolve(expr, ctx) == left // right
    pred = expr == left // right
    assert evaluate(pred, ctx)
    assert compile_predicate(pred)(ctx)
    assert resolve(left // (N.n - left + right), ctx) == left // right


@pytest.mark.parametrize(
    "left,right,error",
    [(1, 0, ZeroDivisionError), (1.0, 2, TypeError), (True, 2, TypeError), (2, False, TypeError)],
)
def test_interpreter_and_compiler_report_identical_errors(left, right, error):
    pred = _FloorDivExpr(left, right) == 0
    messages = []
    for run in (lambda: evaluate(pred, {}), lambda: compile_predicate(pred)({})):
        with pytest.raises(error) as caught:
            run()
        messages.append(str(caught.value))
    assert messages[0] == messages[1]


def test_binding_where_scopes_and_quantifiers():
    class N(Entity):
        n: int = Field(5, ge=-10, le=10)

    m, lev, total = Param("m", 1, 2), Param("lev", 2, 3), Param("total", 4, 5)
    family = Action(
        id="margin", params=[m, lev, total], where=[m == total // lev], effect=[Set(N.n, m)]
    )
    spec = Spec(id="s", name="S", actions=[family])
    assert len(spec.actions) == 4
    holder = Param("holder", N)
    assert resolve(_resolve(holder.n // 2, {"holder": N}), {N: N()}) == 2
    scope = Scope(N, keys=["one"], id="numbers")
    x = Bound("x", scope)
    pred = ForAll(x, x.n // 2 == 2)
    ctx = {scope["one"]: scope["one"]()}
    assert evaluate(pred, ctx) and compile_predicate(pred)(ctx)
    assert resolve(scope["one"].n // 2, ctx) == 2


@pytest.mark.parametrize("divisor", [-2, 2])
@pytest.mark.parametrize("numerator", [-5, 5])
def test_tlc_agrees_with_negative_floor(numerator, divisor):
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))

    class N(Entity):
        n: int = numerator
        out: int = Field(0, ge=-10, le=10)
        done: bool = False

    action = Action(
        id="divide", pre=[Not(N.done)], effect=[Set(N.out, N.n // divisor), Set(N.done, True)]
    )
    query = AlwaysHolds(Or(Not(N.done), N.out == numerator // divisor), id="safe")
    spec = Spec(id="s", name="S", actions=[action], queries=[query])
    assert validate_spec(spec).verdict == "PASS"
    result = validate_spec(spec, max_states=1, tlc=True)
    assert result.verdict == "PASS"
    assert result.query_results[0].backend == "tlc"


def test_dynamic_zero_is_a_finding_and_tlc_refuses_unknown_divisor():
    class N(Entity):
        d: int = Field(1, ge=0, le=1)

    zero = Action(id="zero", effect=[Set(N.d, 0)])
    query = AlwaysHolds(1 // N.d >= 0, id="safe")
    spec = Spec(id="s", name="S", actions=[zero], queries=[query])
    for sliced in (False, True):
        result = validate_spec(spec, sliced=sliced)
        assert result.verdict == "FAIL"
        assert any("division by zero" in f.message for f in result.query_results[0].findings)
    roots, _ = build_canonical_initials(spec)
    with pytest.raises(ExportError, match="constant integer divisor"):
        export_tla(spec, roots, target=Target("always", query.predicate))
    query.predicate = N.d // 0 >= 0
    assert any(
        f.severity == "ERROR" and "division by zero" in f.message
        for f in validate_spec(spec).structural_findings
    )
