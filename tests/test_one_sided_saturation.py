"""Clamping a selected bound never disables the remaining field constraints."""

import pytest

from analint import Action, AlwaysHolds, Create, Entity, Field, Implies, Present, Scope, Set, Spec
from analint.backends.tlc import TlcUnavailable, find_tlc
from analint.validator.engine import validate_spec
from analint.validator.kernel import Outcome, step


@pytest.mark.parametrize(
    "mode,value,expected",
    [
        ("low", -1, 0),
        ("low", 3, None),
        ("high", 3, 2),
        ("high", -1, None),
        (True, -1, 0),
        (True, 3, 2),
        (False, -1, None),
        (False, 3, None),
    ],
)
@pytest.mark.parametrize("create", [False, True])
def test_selected_bound_clamps_and_opposite_bound_fails(mode, value, expected, create):
    class Box(Entity):
        n: int = Field(1, ge=0, le=2, saturate=mode)

    if create:
        scope = Scope(Box, keys=["one"], initially_present=False, id="boxes")
        ref = scope["one"]
        action = Action(id="change", effect=[Create(ref, n=value)])
        from analint import Absent

        context = {ref: Absent(ref)}
        field = ref.n
    else:
        action = Action(id="change", effect=[Set(Box.n, value)])
        context = {Box: Box()}
        ref, field = Box, Box.n
    spec = Spec(id="s", name="S", actions=[action])
    result = step(spec, action, context)
    assert result.outcome == (Outcome.DEFECT if expected is None else Outcome.ACCEPTED)
    if expected is not None:
        assert result.post_context[ref].n == expected
    assert context[ref].__dict__.get("n") == (None if create else 1)
    spec.queries = [
        AlwaysHolds(Implies(Present(ref), field >= 0) if create else field >= 0, id="safe")
    ]
    for sliced in (False, True):
        report = validate_spec(spec, sliced=sliced)
        assert report.verdict == ("FAIL" if expected is None else "PASS")


@pytest.mark.parametrize("mode", ["low", "high"])
@pytest.mark.parametrize("defect", [False, True])
@pytest.mark.parametrize("create", [False, True])
def test_tlc_preserves_one_sided_bound(mode, defect, create):
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))

    class Box(Entity):
        n: int = Field(1, ge=0, le=2, saturate=mode)

    value = (3 if mode == "low" else -1) if defect else (-1 if mode == "low" else 3)
    if create:
        scope = Scope(Box, keys=["one"], initially_present=False, id="boxes")
        ref = scope["one"]
        action = Action(id="change", effect=[Create(ref, n=value)])
        query = AlwaysHolds(Implies(Present(ref), ref.n >= 0), id="safe")
    else:
        action = Action(id="change", pre=[Box.n == 1], effect=[Set(Box.n, value)])
        query = AlwaysHolds(Box.n >= 0, id="safe")
    spec = Spec(id="s", name="S", actions=[action], queries=[query])
    native = validate_spec(spec)
    fallback = validate_spec(spec, max_states=1, tlc=True)
    assert fallback.verdict == native.verdict == ("FAIL" if defect else "PASS")


@pytest.mark.parametrize(
    "mode,kwargs", [("low", {}), ("high", {}), (True, {"ge": 0}), ("both", {}), (1, {})]
)
def test_invalid_saturation_is_rejected(mode, kwargs):
    with pytest.raises(TypeError, match="saturate"):
        Field(0, saturate=mode, **kwargs)


def test_single_bound_and_other_constraints():
    assert Field(0, ge=0, saturate="low").clamp(-1) == 0
    assert Field(0, le=0, saturate="high").clamp(1) == 0

    class Box(Entity):
        n: int = Field(1, ge=0, le=2, values=[1, 2], saturate="low")

    action = Action(id="change", effect=[Set(Box.n, -1)])
    spec = Spec(id="s", name="S", actions=[action])
    assert step(spec, action, {Box: Box()}).outcome == Outcome.DEFECT


def test_mode_changes_cache_identity_and_show_metadata(tmp_path):
    from analint.validator.exploration_cache import digest
    from analint.validator.explorer import build_canonical_initials

    class Box(Entity):
        n: int = Field(1, ge=0, le=2, saturate="low")

    action = Action(id="change", effect=[Set(Box.n, -1)])
    spec = Spec(id="s", name="S", actions=[action])
    roots, _ = build_canonical_initials(spec)
    low = digest(spec, roots, 100, None, frozenset())[0]
    Box.n.spec.saturate = "high"
    high = digest(spec, roots, 100, None, frozenset())[0]
    assert low != high
    from analint.validator.exploration_cache import use_store
    from analint.validator.explorer import explore

    with use_store(tmp_path / "cache"):
        cold = explore(spec, roots, 100)
        warm = explore(spec, roots, 100)
    assert [f.message for f in cold.findings] == [f.message for f in warm.findings]
    assert cold.findings
    from analint.query import _fields_of

    assert _fields_of(Box)[0]["saturate"] == "high"
