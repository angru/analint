"""Host-language safety shared by symbolic DSL values."""


class Symbolic:
    def __bool__(self) -> bool:
        raise TypeError(
            "analint symbolic expressions have no Python truth value; "
            "use And/Or/Not instead of and/or/not, and split chained comparisons"
        )
