"""Cloak of Darkness — the canonical IF benchmark (Roger Firth, 1999) as an analint spec.

Three rooms: Foyer (start), Cloakroom (west), Bar (south). The player wears a
velvet cloak. While the cloak is worn the Bar is dark, and any action in the
dark tramples the message written in sawdust on the floor. Hang the cloak on
the hook in the Cloakroom and the Bar lights up; read the message — if it was
trampled at most once you win, otherwise you lose.
"""

from enum import StrEnum

from analint import (
    Action,
    Add,
    AlwaysHolds,
    DeadActions,
    Entity,
    Expect,
    Field,
    Implies,
    Invariant,
    Lifecycle,
    NoDeadEnd,
    Not,
    Reachable,
    Scenario,
    Set,
    Spec,
)

# ── State ──────────────────────────────────────────────────────────────────────


class Room(StrEnum):
    FOYER = "foyer"
    CLOAKROOM = "cloakroom"
    BAR = "bar"


class Result(StrEnum):
    PLAYING = "playing"
    WON = "won"
    LOST = "lost"


class Player(Entity):
    location: Room = Room.FOYER
    has_cloak: bool = True  # the cloak is worn from the start


class Hook(Entity):
    holds_cloak: bool = False


class Message(Entity):
    # Only the thresholds matter (<=1 legible, >=2 trampled), so the counter
    # saturates at two and keeps the state space finite.
    disturbances: int = Field(0, ge=0, le=2, saturate=True)


class Game(Entity):
    result: Result = Lifecycle(
        initial=Result.PLAYING,
        transitions={Result.PLAYING: [Result.WON, Result.LOST]},
        terminal=[Result.WON, Result.LOST],
    )


# ── Constraints ────────────────────────────────────────────────────────────────

cloak_in_one_place = Invariant(
    Implies(Hook.holds_cloak, Not(Player.has_cloak)),
    label="The cloak cannot be on the hook and on the player at once",
)

# "the Bar is dark" is not stored state — it is a fact derived from the cloak
bar_is_dark = Player.has_cloak
bar_is_lit = Not(Player.has_cloak)

# ── Movement ───────────────────────────────────────────────────────────────────

go_west = Action(
    pre=[Player.location == Room.FOYER],
    effect=[Set(Player.location, Room.CLOAKROOM)],
)

go_east = Action(
    pre=[Player.location == Room.CLOAKROOM],
    effect=[Set(Player.location, Room.FOYER)],
)

go_south = Action(
    pre=[Player.location == Room.FOYER],
    effect=[Set(Player.location, Room.BAR)],
)

go_north = Action(
    pre=[Player.location == Room.BAR],
    effect=[Set(Player.location, Room.FOYER)],
)

# ── The cloak ──────────────────────────────────────────────────────────────────

hang_cloak = Action(
    name="Hang the cloak on the hook",
    pre=[Player.location == Room.CLOAKROOM, Player.has_cloak],
    effect=[Set(Player.has_cloak, False), Set(Hook.holds_cloak, True)],
)

# ── Darkness: any action in the dark Bar tramples the message ─────────────────

grope_in_dark = Action(
    name="Blunder around the dark bar",
    pre=[Player.location == Room.BAR, bar_is_dark],
    effect=[Add(Message.disturbances, 1)],
)

# ── Two endings ────────────────────────────────────────────────────────────────

read_message_win = Action(
    name="Read the message (legible)",
    pre=[Player.location == Room.BAR, bar_is_lit, Message.disturbances <= 1],
    effect=[Set(Game.result, Result.WON)],
)

read_message_lose = Action(
    name="Read the message (trampled)",
    pre=[Player.location == Room.BAR, bar_is_lit, Message.disturbances >= 2],
    effect=[Set(Game.result, Result.LOST)],
)

# ── Scenarios ──────────────────────────────────────────────────────────────────

sc_walk_west = Scenario(
    name="Walk from the foyer to the cloakroom",
    action=go_west,
    given=[Player()],
    then=[Player.location == Room.CLOAKROOM],
)

sc_walk_back = Scenario(
    name="Walk back east to the foyer",
    action=go_east,
    given=[Player(location=Room.CLOAKROOM)],
    then=[Player.location == Room.FOYER],
)

sc_walk_south = Scenario(
    name="Walk south into the bar",
    action=go_south,
    given=[Player()],
    then=[Player.location == Room.BAR],
)

sc_walk_north = Scenario(
    name="Leave the bar to the north",
    action=go_north,
    given=[Player(location=Room.BAR)],
    then=[Player.location == Room.FOYER],
)

sc_hang = Scenario(
    name="Hang the cloak in the cloakroom",
    action=hang_cloak,
    given=[Player(location=Room.CLOAKROOM, has_cloak=True), Hook()],
    then=[
        Not(Player.has_cloak),
        Hook.holds_cloak,
    ],
)

sc_hang_from_foyer = Scenario(
    name="Cannot hang the cloak from another room",
    action=hang_cloak,
    given=[Player(location=Room.FOYER, has_cloak=True), Hook()],
    expected=Expect.FAIL,
)

sc_grope = Scenario(
    name="Blundering in the dark tramples the message",
    action=grope_in_dark,
    given=[Player(location=Room.BAR, has_cloak=True), Message(disturbances=0)],
    then=[Message.disturbances == 1],
)

sc_read_in_dark = Scenario(
    name="The message cannot be read in the dark",
    action=read_message_win,
    given=[
        Player(location=Room.BAR, has_cloak=True),
        Message(disturbances=0),
        Game(),
    ],
    expected=Expect.FAIL,
)

sc_clean_win = Scenario(
    name="Undisturbed message — the player wins",
    action=read_message_win,
    given=[
        Player(location=Room.BAR, has_cloak=False),
        Hook(holds_cloak=True),
        Message(disturbances=0),
        Game(),
    ],
    then=[Game.result == Result.WON],
)

sc_trampled_lose = Scenario(
    name="Trampled message — the player loses",
    action=read_message_lose,
    given=[
        Player(location=Room.BAR, has_cloak=False),
        Hook(holds_cloak=True),
        Message(disturbances=2),
        Game(),
    ],
    then=[Game.result == Result.LOST],
)

sc_game_already_over = Scenario(
    name="A finished game cannot be re-finished",
    action=read_message_win,
    given=[
        Player(location=Room.BAR, has_cloak=False),
        Hook(holds_cloak=True),
        Message(disturbances=0),
        Game(result=Result.WON),  # terminal → blocked
    ],
    expected=Expect.FAIL,
)

# ── Reachability queries ───────────────────────────────────────────────────────

win_is_reachable = Reachable(
    Game.result == Result.WON,
    label="the player can win",
)

lose_is_reachable = Reachable(
    Game.result == Result.LOST,
    label="the player can lose (otherwise why model it)",
)

game_can_always_end = NoDeadEnd(
    goal=Game.result != Result.PLAYING,
    label="the player can never get stuck",
)

every_action_playable = DeadActions()

cloak_invariant_holds_everywhere = AlwaysHolds(
    Implies(Hook.holds_cloak, Not(Player.has_cloak)),
    label="the cloak is never in two places",
)

# ── Spec — everything above is discovered automatically ───────────────────────

spec = Spec(
    id="cloak-of-darkness",
    name="Cloak of Darkness",
    version="1.0.0",
    description="The classic IF benchmark expressed as verifiable game rules",
)
