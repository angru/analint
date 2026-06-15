"""Arithmetic expressions over fields — serializable AST nodes, not Python math.

Built by operator overloading on fields (and params), evaluated against a
state by `resolve()`:

    Wallet.balance - Order.total >= 0          # predicate over an expression
    total = Alice.coins + Bob.coins + Eve.coins  # named, reusable expression
    Set(src.coins, src.coins - amount)         # canonical effect form:
                                               # "the next value IS this expression"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analint.models.predicate import Predicate


class Expr:
    """Base class for arithmetic expression nodes."""

    # chaining arithmetic ──────────────────────────────────────────────────────

    def __add__(self, other: Any) -> Expr:
        return _AddExpr(self, other)

    def __radd__(self, other: Any) -> Expr:
        return _AddExpr(other, self)

    def __sub__(self, other: Any) -> Expr:
        return _SubExpr(self, other)

    def __rsub__(self, other: Any) -> Expr:
        return _SubExpr(other, self)

    def __mul__(self, other: Any) -> Expr:
        return _MulExpr(self, other)

    def __rmul__(self, other: Any) -> Expr:
        return _MulExpr(other, self)

    # comparisons produce predicates ───────────────────────────────────────────

    def __eq__(self, other: Any) -> Predicate:  # type: ignore
        from analint.models.predicate import _Eq

        return _Eq(left=self, right=other)

    def __ne__(self, other: Any) -> Predicate:  # type: ignore
        from analint.models.predicate import _Ne

        return _Ne(left=self, right=other)

    def __gt__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Gt

        return _Gt(left=self, right=other)

    def __ge__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Gte

        return _Gte(left=self, right=other)

    def __lt__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Lt

        return _Lt(left=self, right=other)

    def __le__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Lte

        return _Lte(left=self, right=other)

    def __hash__(self) -> int:
        return id(self)


@dataclass(eq=False)
class _BinaryExpr(Expr):
    """Closed base for the binary arithmetic nodes — carries typed operands so
    traversal can read ``.left``/``.right`` without an attr-defined suppression."""

    left: Any
    right: Any


@dataclass(eq=False)
class _AddExpr(_BinaryExpr):
    pass


@dataclass(eq=False)
class _SubExpr(_BinaryExpr):
    pass


@dataclass(eq=False)
class _MulExpr(_BinaryExpr):
    pass


_OPS: dict[type, str] = {_AddExpr: "+", _SubExpr: "-", _MulExpr: "*"}


def expr_op(expr: Expr) -> str:
    return _OPS[type(expr)]
