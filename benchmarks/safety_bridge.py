"""A bridge constraint must not couple an already-proved local safety query."""

from analint import Action, Add, AlwaysHolds, Entity, Field, Invariant, Scenario, Spec, Unreachable


class A(Entity):
    n: int = Field(0, ge=0, le=3)


class B(Entity):
    n: int = Field(0, ge=0, le=20)


bump_a = Action(id="bump_a", pre=[A.n < 3], effect=[Add(A.n, 1)])
bump_b = Action(id="bump_b", pre=[B.n < 20], effect=[Add(B.n, 1)])
bounded_a = Invariant(A.n <= 3, id="bounded_a")
bridge = Invariant(A.n <= B.n, id="bridge")
bounded_b = Invariant(B.n <= 19, id="bounded_b")
safe_a = AlwaysHolds(A.n <= 3, id="safe_a")
never_overflow = Unreachable(A.n > 3, id="never_overflow")
spec = Spec(
    id="safety_bridge",
    name="Safety proof across a bridge",
    actions=[bump_a, bump_b],
    invariants=[bounded_a, bridge, bounded_b],
    queries=[safe_a, never_overflow],
    scenarios=[
        Scenario(id="a_example", action=bump_a, given=[A(), B(n=3)]),
        Scenario(id="b_example", action=bump_b, given=[A(), B()]),
    ],
)
