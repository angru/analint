"""A spec whose only query cannot finish within budget — used to test that
INCONCLUSIVE never reads as a green PASS."""

from analint import Action, Add, Entity, Field, Spec, Unreachable


class Counter(Entity):
    n: int = Field(0, ge=0)  # deliberately unbounded


tick = Action(id="tick", effect=[Add(Counter.n, 1)])

# n climbs forever; the engine cannot prove this within max_states.
never = Unreachable(Counter.n == 999_999, id="never", max_states=200)

spec = Spec(id="inc", name="Inconclusive")
