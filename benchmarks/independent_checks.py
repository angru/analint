"""Independent components: B's broken invariant does not refute A's safety."""

from analint import Action, Add, AlwaysHolds, Entity, Field, Invariant, Scenario, Spec


class A(Entity):
    n: int = Field(0, ge=0, le=3)


class B(Entity):
    n: int = Field(0, ge=0, le=20)


bump_a = Action(id="bump_a", pre=[A.n < 3], effect=[Add(A.n, 1)])
bump_b = Action(id="bump_b", pre=[B.n < 20], effect=[Add(B.n, 1)])
bounded_a = Invariant(A.n <= 3, id="bounded_a")
bounded_b = Invariant(B.n <= 19, id="bounded_b")
safe_a = AlwaysHolds(A.n <= 3, id="safe_a")
safe_sum = AlwaysHolds(A.n + B.n <= 23, id="safe_sum")
a_example = Scenario(id="a_example", action=bump_a, given=[A()])
b_example = Scenario(id="b_example", action=bump_b, given=[B()])
spec = Spec(
    id="independent_checks",
    name="Independent check scopes",
    actions=[bump_a, bump_b],
    invariants=[bounded_a, bounded_b],
    queries=[safe_a, safe_sum],
    scenarios=[a_example, b_example],
)
