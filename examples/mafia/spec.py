"""Mafia / Werewolf, translated from Quint's play_mafia.qnt.

Original:
https://github.com/quint-co/quint/blob/main/examples/games/mafia_werewolf/play_mafia.qnt

Quint models players as maps and chooses every role assignment nondeterministically
in ``init``. analint explores one instance per entity type, so this translation
fixes the example table to the classic three-player setup: Mahtab is Mafia;
Gabriela and Max are Citizens. Quint's nondeterministic player choices become
finite ``Param`` action families.
"""

from enum import StrEnum

from analint import (
    Action,
    Add,
    AlwaysHolds,
    And,
    Assert,
    Entity,
    Expect,
    Field,
    Implies,
    Invariant,
    Lifecycle,
    Or,
    Param,
    Reachable,
    Scenario,
    Set,
    Spec,
    Transition,
    Unreachable,
)


class Role(StrEnum):
    MAFIA = "mafia"
    CITIZEN = "citizen"


class Phase(StrEnum):
    DAY = "day"
    NIGHT = "night"


class GameStatus(StrEnum):
    PENDING = "pending"
    MAFIA_WON = "mafia_won"
    CITIZENS_WON = "citizens_won"


class Mahtab(Entity):
    role: Role = Role.MAFIA
    alive: bool = True
    voted: bool = False
    votes: int = Field(0, ge=0, le=2)


class Gabriela(Entity):
    role: Role = Role.CITIZEN
    alive: bool = True
    voted: bool = False
    votes: int = Field(0, ge=0, le=2)


class Max(Entity):
    role: Role = Role.CITIZEN
    alive: bool = True
    voted: bool = False
    votes: int = Field(0, ge=0, le=2)


class Game(Entity):
    phase: Phase = Phase.NIGHT
    status: GameStatus = Lifecycle(
        initial=GameStatus.PENDING,
        transitions=[
            Transition(
                GameStatus.PENDING,
                [GameStatus.MAFIA_WON, GameStatus.CITIZENS_WON],
            )
        ],
        terminal=[GameStatus.MAFIA_WON, GameStatus.CITIZENS_WON],
    )


# A dead player need not vote; every living player must vote before resolution.
all_voted = And(
    Implies(Mahtab.alive == True, Mahtab.voted == True),  # noqa: E712
    Implies(Gabriela.alive == True, Gabriela.voted == True),  # noqa: E712
    Implies(Max.alive == True, Max.voted == True),  # noqa: E712
)

correct_game_status = Invariant(
    And(
        Implies(
            Game.status == GameStatus.CITIZENS_WON,
            Mahtab.alive == False,  # noqa: E712
        ),
        Implies(
            Game.status == GameStatus.MAFIA_WON,
            And(
                Gabriela.alive == False,  # noqa: E712
                Max.alive == False,  # noqa: E712
            ),
        ),
        Implies(
            Game.status == GameStatus.PENDING,
            And(
                Mahtab.alive == True,  # noqa: E712
                Or(
                    Gabriela.alive == True,  # noqa: E712
                    Max.alive == True,  # noqa: E712
                ),
            ),
        ),
    ),
    label="Game status matches the surviving roles",
)


# Night: the Mafia kills one living Citizen. The last Citizen's death ends the
# game; otherwise play moves to the Day phase.
mafia_kills_gabriela = Action(
    pre=[
        Game.phase == Phase.NIGHT,
        Game.status == GameStatus.PENDING,
        Mahtab.alive == True,  # noqa: E712
        Gabriela.alive == True,  # noqa: E712
        Max.alive == True,  # noqa: E712
    ],
    effect=[
        Set(Gabriela.alive, False),
        Set(Game.phase, Phase.DAY),
    ],
)

mafia_kills_max = Action(
    pre=[
        Game.phase == Phase.NIGHT,
        Game.status == GameStatus.PENDING,
        Mahtab.alive == True,  # noqa: E712
        Max.alive == True,  # noqa: E712
        Gabriela.alive == True,  # noqa: E712
    ],
    effect=[
        Set(Max.alive, False),
        Set(Game.phase, Phase.DAY),
    ],
)

mafia_kills_last_gabriela = Action(
    pre=[
        Game.phase == Phase.NIGHT,
        Game.status == GameStatus.PENDING,
        Mahtab.alive == True,  # noqa: E712
        Gabriela.alive == True,  # noqa: E712
        Max.alive == False,  # noqa: E712
    ],
    effect=[
        Set(Gabriela.alive, False),
        Set(Game.status, GameStatus.MAFIA_WON),
    ],
)

mafia_kills_last_max = Action(
    pre=[
        Game.phase == Phase.NIGHT,
        Game.status == GameStatus.PENDING,
        Mahtab.alive == True,  # noqa: E712
        Max.alive == True,  # noqa: E712
        Gabriela.alive == False,  # noqa: E712
    ],
    effect=[
        Set(Max.alive, False),
        Set(Game.status, GameStatus.MAFIA_WON),
    ],
)


# Day: every living player chooses one other living player.
voter = Param("voter", Mahtab, Gabriela, Max)
target = Param("target", Mahtab, Gabriela, Max)

vote = Action(
    params=[voter, target],
    where=[voter != target],
    pre=[
        Game.phase == Phase.DAY,
        Game.status == GameStatus.PENDING,
        voter.alive == True,  # noqa: E712
        target.alive == True,  # noqa: E712
        voter.voted == False,  # noqa: E712
    ],
    effect=[
        Set(voter.voted, True),
        Add(target.votes, 1),
    ],
)


reset_ballot = [
    Set(Mahtab.voted, False),
    Set(Gabriela.voted, False),
    Set(Max.voted, False),
    Set(Mahtab.votes, 0),
    Set(Gabriela.votes, 0),
    Set(Max.votes, 0),
]


mahtab_has_unique_max = And(
    Mahtab.votes > Gabriela.votes,
    Mahtab.votes > Max.votes,
)
gabriela_has_unique_max = And(
    Gabriela.votes > Mahtab.votes,
    Gabriela.votes > Max.votes,
)
max_has_unique_max = And(
    Max.votes > Mahtab.votes,
    Max.votes > Gabriela.votes,
)

hang_mahtab = Action(
    pre=[
        Game.phase == Phase.DAY,
        Game.status == GameStatus.PENDING,
        all_voted,
        Mahtab.alive == True,  # noqa: E712
        mahtab_has_unique_max,
    ],
    effect=[
        Set(Mahtab.alive, False),
        Set(Game.status, GameStatus.CITIZENS_WON),
        *reset_ballot,
    ],
)

hang_gabriela = Action(
    pre=[
        Game.phase == Phase.DAY,
        Game.status == GameStatus.PENDING,
        all_voted,
        Gabriela.alive == True,  # noqa: E712
        Max.alive == True,  # noqa: E712
        gabriela_has_unique_max,
    ],
    effect=[
        Set(Gabriela.alive, False),
        Set(Game.phase, Phase.NIGHT),
        *reset_ballot,
    ],
)

hang_max = Action(
    pre=[
        Game.phase == Phase.DAY,
        Game.status == GameStatus.PENDING,
        all_voted,
        Max.alive == True,  # noqa: E712
        Gabriela.alive == True,  # noqa: E712
        max_has_unique_max,
    ],
    effect=[
        Set(Max.alive, False),
        Set(Game.phase, Phase.NIGHT),
        *reset_ballot,
    ],
)

hang_last_gabriela = Action(
    pre=[
        Game.phase == Phase.DAY,
        Game.status == GameStatus.PENDING,
        all_voted,
        Gabriela.alive == True,  # noqa: E712
        Max.alive == False,  # noqa: E712
        gabriela_has_unique_max,
    ],
    effect=[
        Set(Gabriela.alive, False),
        Set(Game.status, GameStatus.MAFIA_WON),
        *reset_ballot,
    ],
)

hang_last_max = Action(
    pre=[
        Game.phase == Phase.DAY,
        Game.status == GameStatus.PENDING,
        all_voted,
        Max.alive == True,  # noqa: E712
        Gabriela.alive == False,  # noqa: E712
        max_has_unique_max,
    ],
    effect=[
        Set(Max.alive, False),
        Set(Game.status, GameStatus.MAFIA_WON),
        *reset_ballot,
    ],
)

top_vote_is_tied = Or(
    And(Mahtab.votes == Gabriela.votes, Mahtab.votes >= Max.votes),
    And(Mahtab.votes == Max.votes, Mahtab.votes >= Gabriela.votes),
    And(Gabriela.votes == Max.votes, Gabriela.votes >= Mahtab.votes),
)

votes_tied = Action(
    pre=[
        Game.phase == Phase.DAY,
        Game.status == GameStatus.PENDING,
        all_voted,
        top_vote_is_tied,
    ],
    effect=[
        Set(Game.phase, Phase.NIGHT),
        *reset_ballot,
    ],
)


def _world(
    *,
    phase: Phase = Phase.NIGHT,
    status: GameStatus = GameStatus.PENDING,
    mahtab_alive: bool = True,
    gabriela_alive: bool = True,
    max_alive: bool = True,
    mahtab_voted: bool = False,
    gabriela_voted: bool = False,
    max_voted: bool = False,
    mahtab_votes: int = 0,
    gabriela_votes: int = 0,
    max_votes: int = 0,
) -> list:
    return [
        Mahtab(alive=mahtab_alive, voted=mahtab_voted, votes=mahtab_votes),
        Gabriela(alive=gabriela_alive, voted=gabriela_voted, votes=gabriela_votes),
        Max(alive=max_alive, voted=max_voted, votes=max_votes),
        Game(phase=phase, status=status),
    ]


sc_mafia_kills_gabriela = Scenario(
    action=mafia_kills_gabriela,
    given=_world(),
    then=[
        Assert(Gabriela.alive == False),  # noqa: E712
        Assert(Game.phase == Phase.DAY),
    ],
)

sc_mafia_kills_max = Scenario(
    action=mafia_kills_max,
    given=_world(),
    then=[Assert(Max.alive == False), Assert(Game.phase == Phase.DAY)],  # noqa: E712
)

sc_mafia_wins_by_killing_gabriela = Scenario(
    action=mafia_kills_last_gabriela,
    given=_world(max_alive=False),
    then=[Assert(Game.status == GameStatus.MAFIA_WON)],
)

sc_mafia_wins_by_killing_max = Scenario(
    action=mafia_kills_last_max,
    given=_world(gabriela_alive=False),
    then=[Assert(Game.status == GameStatus.MAFIA_WON)],
)

sc_living_player_votes = Scenario(
    action=vote.bind(voter=Gabriela, target=Mahtab),
    given=_world(phase=Phase.DAY),
    then=[
        Assert(Gabriela.voted == True),  # noqa: E712
        Assert(Mahtab.votes == 1),
    ],
)

sc_player_cannot_vote_twice = Scenario(
    action=vote.bind(voter=Gabriela, target=Mahtab),
    given=_world(phase=Phase.DAY, gabriela_voted=True),
    expected=Expect.FAIL,
)

sc_citizens_hang_mafia = Scenario(
    action=hang_mahtab,
    given=_world(
        phase=Phase.DAY,
        mahtab_voted=True,
        gabriela_voted=True,
        max_voted=True,
        mahtab_votes=2,
        gabriela_votes=1,
    ),
    then=[Assert(Game.status == GameStatus.CITIZENS_WON)],
)

sc_hang_gabriela = Scenario(
    action=hang_gabriela,
    given=_world(
        phase=Phase.DAY,
        mahtab_voted=True,
        gabriela_voted=True,
        max_voted=True,
        gabriela_votes=2,
        max_votes=1,
    ),
    then=[
        Assert(Gabriela.alive == False),  # noqa: E712
        Assert(Game.phase == Phase.NIGHT),
    ],
)

sc_hang_max = Scenario(
    action=hang_max,
    given=_world(
        phase=Phase.DAY,
        mahtab_voted=True,
        gabriela_voted=True,
        max_voted=True,
        max_votes=2,
        gabriela_votes=1,
    ),
    then=[Assert(Max.alive == False), Assert(Game.phase == Phase.NIGHT)],  # noqa: E712
)

sc_mafia_wins_when_last_gabriela_is_hanged = Scenario(
    action=hang_last_gabriela,
    given=_world(
        phase=Phase.DAY,
        max_alive=False,
        mahtab_voted=True,
        gabriela_voted=True,
        gabriela_votes=1,
    ),
    then=[Assert(Game.status == GameStatus.MAFIA_WON)],
)

sc_mafia_wins_when_last_max_is_hanged = Scenario(
    action=hang_last_max,
    given=_world(
        phase=Phase.DAY,
        gabriela_alive=False,
        mahtab_voted=True,
        max_voted=True,
        max_votes=1,
    ),
    then=[Assert(Game.status == GameStatus.MAFIA_WON)],
)

sc_tie_skips_hanging = Scenario(
    action=votes_tied,
    given=_world(
        phase=Phase.DAY,
        mahtab_voted=True,
        gabriela_voted=True,
        max_voted=True,
        mahtab_votes=1,
        gabriela_votes=1,
        max_votes=1,
    ),
    then=[
        Assert(Game.phase == Phase.NIGHT),
        Assert(Mahtab.alive == True),  # noqa: E712
        Assert(Mahtab.votes == 0),
    ],
)


citizens_cannot_win_from_this_setup = Unreachable(
    Game.status == GameStatus.CITIZENS_WON,
    label="Night-first play with three players prevents a Citizen win",
)

mafia_can_win = Reachable(
    Game.status == GameStatus.MAFIA_WON,
    label="Mafia can eliminate both Citizens",
)

status_is_always_correct = AlwaysHolds(
    And(
        Implies(
            Game.status == GameStatus.CITIZENS_WON,
            Mahtab.alive == False,  # noqa: E712
        ),
        Implies(
            Game.status == GameStatus.MAFIA_WON,
            And(
                Gabriela.alive == False,  # noqa: E712
                Max.alive == False,  # noqa: E712
            ),
        ),
    ),
    label="A declared winner really eliminated the opposing role",
)

spec = Spec(
    id="mafia",
    name="Mafia / Werewolf (Quint translation)",
    version="1.0.0",
    description="A fixed three-player Mafia game translated from Quint's "
    "play_mafia.qnt, with parameterized voting and bounded exploration",
)
