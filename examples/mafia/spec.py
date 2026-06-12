"""Mafia / Werewolf, translated from Quint's play_mafia.qnt.

Original:
https://github.com/quint-co/quint/blob/main/examples/games/mafia_werewolf/play_mafia.qnt

Quint models players as maps and chooses every role assignment
nondeterministically in ``init``. analint explores one instance per entity
type, so the three players are fixed entities — but the role assignment is
NOT fixed: the queries quantify over the finite set of admissible initial
states via ``given_any`` (research/16), and the actions are role-generic
``Param`` families, never naming the mafia player. Quint's nondeterministic
player choices become finite ``Param`` bindings; Quint's nondeterministic
``init`` becomes the initial-state set.

The headline theorem: in the 3-player night-first game the citizens cannot
win — under EVERY role assignment, not just a convenient one.
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


_PLAYERS = [Mahtab, Gabriela, Max]

# A dead player need not vote; every living player must vote before resolution.
all_voted = And(
    Implies(Mahtab.alive == True, Mahtab.voted == True),  # noqa: E712
    Implies(Gabriela.alive == True, Gabriela.voted == True),  # noqa: E712
    Implies(Max.alive == True, Max.voted == True),  # noqa: E712
)

# Role-generic world facts (the quantifier expanded by hand over the three
# fixed players — the multiplicity wall, measured again).
mafia_is_dead = And(
    Implies(Mahtab.role == Role.MAFIA, Mahtab.alive == False),  # noqa: E712
    Implies(Gabriela.role == Role.MAFIA, Gabriela.alive == False),  # noqa: E712
    Implies(Max.role == Role.MAFIA, Max.alive == False),  # noqa: E712
)
mafia_is_alive = Or(
    And(Mahtab.role == Role.MAFIA, Mahtab.alive == True),  # noqa: E712
    And(Gabriela.role == Role.MAFIA, Gabriela.alive == True),  # noqa: E712
    And(Max.role == Role.MAFIA, Max.alive == True),  # noqa: E712
)
all_citizens_dead = And(
    Implies(Mahtab.role == Role.CITIZEN, Mahtab.alive == False),  # noqa: E712
    Implies(Gabriela.role == Role.CITIZEN, Gabriela.alive == False),  # noqa: E712
    Implies(Max.role == Role.CITIZEN, Max.alive == False),  # noqa: E712
)
some_citizen_alive = Or(
    And(Mahtab.role == Role.CITIZEN, Mahtab.alive == True),  # noqa: E712
    And(Gabriela.role == Role.CITIZEN, Gabriela.alive == True),  # noqa: E712
    And(Max.role == Role.CITIZEN, Max.alive == True),  # noqa: E712
)

correct_game_status = Invariant(
    And(
        Implies(Game.status == GameStatus.CITIZENS_WON, mafia_is_dead),
        Implies(Game.status == GameStatus.MAFIA_WON, all_citizens_dead),
        Implies(Game.status == GameStatus.PENDING, And(mafia_is_alive, some_citizen_alive)),
    ),
    label="Game status matches the surviving roles",
)


# ── Night: the Mafia kills one living Citizen ─────────────────────────────────
# Role-generic: killer/victim/bystander are parameters; the role guards live
# in `pre`, so the same declarations work for every role assignment.

killer = Param("killer", *_PLAYERS)
victim = Param("victim", *_PLAYERS)
bystander = Param("bystander", *_PLAYERS)

_night = [Game.phase == Phase.NIGHT, Game.status == GameStatus.PENDING]
_distinct3 = [killer != victim, killer != bystander, victim != bystander]

mafia_kills = Action(
    name="Mafia kills a citizen; another citizen survives",
    params=[killer, victim, bystander],
    where=_distinct3,
    pre=[
        *_night,
        killer.role == Role.MAFIA,
        killer.alive == True,  # noqa: E712
        victim.role == Role.CITIZEN,
        victim.alive == True,  # noqa: E712
        bystander.alive == True,  # noqa: E712
    ],
    effect=[Set(victim.alive, False), Set(Game.phase, Phase.DAY)],
)

mafia_kills_last_citizen = Action(
    name="Mafia kills the last citizen — game over",
    params=[killer, victim, bystander],
    where=_distinct3,
    pre=[
        *_night,
        killer.role == Role.MAFIA,
        killer.alive == True,  # noqa: E712
        victim.role == Role.CITIZEN,
        victim.alive == True,  # noqa: E712
        bystander.alive == False,  # noqa: E712
    ],
    effect=[Set(victim.alive, False), Set(Game.status, GameStatus.MAFIA_WON)],
)


# ── Day: every living player votes for another living player ─────────────────

voter = Param("voter", *_PLAYERS)
target = Param("target", *_PLAYERS)

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
    effect=[Set(voter.voted, True), Add(target.votes, 1)],
)


reset_ballot = [
    Set(Mahtab.voted, False),
    Set(Gabriela.voted, False),
    Set(Max.voted, False),
    Set(Mahtab.votes, 0),
    Set(Gabriela.votes, 0),
    Set(Max.votes, 0),
]

# ── Day resolution: hang whoever holds a unique vote maximum ──────────────────

hanged = Param("hanged", *_PLAYERS)
other_a = Param("other_a", *_PLAYERS)
other_b = Param("other_b", *_PLAYERS)

_day = [Game.phase == Phase.DAY, Game.status == GameStatus.PENDING, all_voted]
_distinct_hang = [hanged != other_a, hanged != other_b, other_a != other_b]
_unique_max = [hanged.votes > other_a.votes, hanged.votes > other_b.votes]

hang_mafia = Action(
    name="The town hangs the mafia — citizens win",
    params=[hanged, other_a, other_b],
    where=_distinct_hang,
    pre=[
        *_day,
        hanged.alive == True,  # noqa: E712
        hanged.role == Role.MAFIA,
        *_unique_max,
    ],
    effect=[Set(hanged.alive, False), Set(Game.status, GameStatus.CITIZENS_WON), *reset_ballot],
)

hang_citizen = Action(
    name="The town hangs a citizen; the game goes on",
    params=[hanged, other_a, other_b],
    where=_distinct_hang,
    pre=[
        *_day,
        hanged.alive == True,  # noqa: E712
        hanged.role == Role.CITIZEN,
        *_unique_max,
        # another citizen is still alive
        Or(
            And(other_a.role == Role.CITIZEN, other_a.alive == True),  # noqa: E712
            And(other_b.role == Role.CITIZEN, other_b.alive == True),  # noqa: E712
        ),
    ],
    effect=[Set(hanged.alive, False), Set(Game.phase, Phase.NIGHT), *reset_ballot],
)

hang_last_citizen = Action(
    name="The town hangs the last citizen — mafia wins",
    params=[hanged, other_a, other_b],
    where=_distinct_hang,
    pre=[
        *_day,
        hanged.alive == True,  # noqa: E712
        hanged.role == Role.CITIZEN,
        *_unique_max,
        Implies(other_a.role == Role.CITIZEN, other_a.alive == False),  # noqa: E712
        Implies(other_b.role == Role.CITIZEN, other_b.alive == False),  # noqa: E712
    ],
    effect=[Set(hanged.alive, False), Set(Game.status, GameStatus.MAFIA_WON), *reset_ballot],
)

top_vote_is_tied = Or(
    And(Mahtab.votes == Gabriela.votes, Mahtab.votes >= Max.votes),
    And(Mahtab.votes == Max.votes, Mahtab.votes >= Gabriela.votes),
    And(Gabriela.votes == Max.votes, Gabriela.votes >= Mahtab.votes),
)

votes_tied = Action(
    name="No unique maximum — nobody hangs, night falls",
    pre=[*_day, top_vote_is_tied],
    effect=[Set(Game.phase, Phase.NIGHT), *reset_ballot],
)


# ── Worlds ─────────────────────────────────────────────────────────────────────


def _world(
    *,
    mafia: type = Mahtab,
    phase: Phase = Phase.NIGHT,
    status: GameStatus = GameStatus.PENDING,
    alive: dict | None = None,
    voted: dict | None = None,
    votes: dict | None = None,
) -> list:
    alive = alive or {}
    voted = voted or {}
    votes = votes or {}
    world: list = [Game(phase=phase, status=status)]
    for player in _PLAYERS:
        world.append(
            player(
                role=Role.MAFIA if player is mafia else Role.CITIZEN,
                alive=alive.get(player, True),
                voted=voted.get(player, False),
                votes=votes.get(player, 0),
            )
        )
    return world


# Quint's nondeterministic init, as a finite set of admissible initial states:
# any of the three players may be the mafia.
any_role_assignment = [_world(mafia=player) for player in _PLAYERS]


# ── Scenarios (one binding each; the queries cover the rest) ──────────────────

sc_night_kill = Scenario(
    action=mafia_kills.bind(killer=Mahtab, victim=Gabriela, bystander=Max),
    given=_world(),
    then=[Assert(Gabriela.alive == False), Assert(Game.phase == Phase.DAY)],  # noqa: E712
)

sc_citizen_cannot_kill = Scenario(
    name="A citizen has no night kill",
    action=mafia_kills.bind(killer=Gabriela, victim=Max, bystander=Mahtab),
    given=_world(),  # Gabriela is a citizen here
    expected=Expect.FAIL,
)

sc_kill_last_citizen_ends_game = Scenario(
    action=mafia_kills_last_citizen.bind(killer=Mahtab, victim=Gabriela, bystander=Max),
    given=_world(alive={Max: False}),
    then=[Assert(Game.status == GameStatus.MAFIA_WON)],
)

sc_vote = Scenario(
    action=vote.bind(voter=Gabriela, target=Mahtab),
    given=_world(phase=Phase.DAY),
    then=[Assert(Mahtab.votes == 1), Assert(Gabriela.voted == True)],  # noqa: E712
)

sc_player_cannot_vote_twice = Scenario(
    action=vote.bind(voter=Gabriela, target=Mahtab),
    given=_world(phase=Phase.DAY, voted={Gabriela: True}),
    expected=Expect.FAIL,
)

sc_dead_player_cannot_vote = Scenario(
    action=vote.bind(voter=Max, target=Mahtab),
    given=_world(phase=Phase.DAY, alive={Max: False}),
    expected=Expect.FAIL,
)

sc_town_hangs_the_mafia = Scenario(
    action=hang_mafia.bind(hanged=Mahtab, other_a=Gabriela, other_b=Max),
    given=_world(
        phase=Phase.DAY,
        voted={Mahtab: True, Gabriela: True, Max: True},
        votes={Mahtab: 2, Gabriela: 1},
    ),
    then=[Assert(Game.status == GameStatus.CITIZENS_WON)],
)

sc_town_hangs_a_citizen = Scenario(
    action=hang_citizen.bind(hanged=Gabriela, other_a=Mahtab, other_b=Max),
    given=_world(
        phase=Phase.DAY,
        voted={Mahtab: True, Gabriela: True, Max: True},
        votes={Gabriela: 2, Mahtab: 1},
    ),
    then=[Assert(Game.phase == Phase.NIGHT), Assert(Game.status == GameStatus.PENDING)],
)

sc_hanging_last_citizen_ends_game = Scenario(
    action=hang_last_citizen.bind(hanged=Max, other_a=Mahtab, other_b=Gabriela),
    given=_world(
        phase=Phase.DAY,
        alive={Gabriela: False},
        voted={Mahtab: True, Max: True},
        votes={Max: 1},
    ),
    then=[Assert(Game.status == GameStatus.MAFIA_WON)],
)

sc_tie_skips_hanging = Scenario(
    action=votes_tied,
    given=_world(
        phase=Phase.DAY,
        voted={Mahtab: True, Gabriela: True, Max: True},
        votes={Mahtab: 1, Gabriela: 1, Max: 1},
    ),
    then=[Assert(Game.phase == Phase.NIGHT)],
)


# ── Queries — quantified over EVERY admissible role assignment ────────────────

mafia_can_win = Reachable(
    Game.status == GameStatus.MAFIA_WON,
    given_any=any_role_assignment,
    label="Mafia can eliminate the citizens",
)

citizens_cannot_win = Unreachable(
    Game.status == GameStatus.CITIZENS_WON,
    given_any=any_role_assignment,
    label="citizens never win the 3-player night-first game — under every role assignment",
)

status_is_always_correct = AlwaysHolds(
    And(
        Implies(Game.status == GameStatus.CITIZENS_WON, mafia_is_dead),
        Implies(Game.status == GameStatus.MAFIA_WON, all_citizens_dead),
    ),
    given_any=any_role_assignment,
    label="the verdict always matches the surviving roles",
)


# ── Spec ───────────────────────────────────────────────────────────────────────

spec = Spec(
    id="mafia",
    name="Mafia / Werewolf (Quint translation)",
    version="1.0.0",
    description="Quint's play_mafia.qnt with role-generic Param actions and "
    "the role assignment quantified as an initial-state set",
)
