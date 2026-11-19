"""Cross-feature gates for the reviewed authoring integration."""

from enum import Enum

import pytest
from rich.console import Console

from analint import (
    Action,
    AlwaysHolds,
    Assert,
    Entity,
    Field,
    Flow,
    Lookup,
    Param,
    Reachable,
    Set,
    Spec,
)
from analint.backends.tla import ExportError, Target, export_tla
from analint.backends.tlc import TlcUnavailable, find_tlc
from analint.reporter import terminal
from analint.validator.engine import validate_spec
from analint.validator.explorer import build_canonical_initials


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("tlc", [False, True])
def test_param_floor_lookup_clamp_flow_and_inherited_budget(
    sliced, tlc, tmp_path, monkeypatch, capsys
):
    if tlc:
        try:
            find_tlc()
        except TlcUnavailable as exc:
            pytest.skip(str(exc))

    class Kind(Enum):
        SMALL = "small"
        LARGE = "large"

    class Box(Entity):
        kind: Kind = Kind.SMALL
        principal: int = 7
        balance: int = Field(7, ge=0, le=8, saturate="low")
        done: bool = False

    divisor = Param("divisor", 2, 4)
    settle = Action(
        id="settle",
        params=[divisor],
        where=[divisor * 2 <= 8],
        pre=[Box.done == False],  # noqa: E712 — DSL predicate
        effect=[
            Set(
                Box.balance,
                Box.principal // divisor - Lookup(Box.kind, {Kind.SMALL: 4, Kind.LARGE: 3}),
            ),
            Set(Box.done, True),
        ],
    )
    query = Reachable(Box.done, id="done")
    spec = Spec(id="combined", name="Combined", actions=[settle], queries=[query], max_states=1)
    spec.flows = [
        Flow(
            id="close",
            name="Close [small]",
            given=[Box()],
            steps=[spec.actions[0], Assert(Box.balance == 0)],
        )
    ]
    assert query.max_states is None
    assert validate_spec(spec, sliced=sliced).query_results[0].status == "INCONCLUSIVE"
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    for cached in (False, True, True):
        result = validate_spec(
            spec, sliced=sliced, max_states=None if tlc else 30, tlc=tlc, cache=cached
        )
        assert result.verdict == "PASS"
        assert result.query_results[0].backend == ("tlc" if tlc else None)
        assert result.flow_results[0].passed
    monkeypatch.setattr(terminal, "console", Console(width=240))
    terminal.report_terminal(result)
    output = capsys.readouterr().out
    assert "close — Close [small]" in output
    assert "[action:settle]" in output


@pytest.mark.parametrize("stored", [False, True])
def test_lookup_as_division_numerator_keeps_explicit_tlc_boundary(stored):
    class Kind(Enum):
        SMALL = "small"
        LARGE = "large"

    class Box(Entity):
        kind: Kind = Kind.SMALL

        value: int = 4

    table = Lookup(Box.kind, {Kind.SMALL: 4, Kind.LARGE: 6})
    change = Action(id="change", effect=[Set(Box.kind, Kind.LARGE), Set(Box.value, table)])
    query = AlwaysHolds((Box.value if stored else table) // 2 >= 2, id="safe")
    spec = Spec(id="boundary", name="Boundary", actions=[change], queries=[query])
    assert validate_spec(spec).verdict == "PASS"
    roots, _ = build_canonical_initials(spec)
    with pytest.raises(ExportError, match="provably integer operands"):
        export_tla(spec, roots, target=Target("always", query.predicate))
