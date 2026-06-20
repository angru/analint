"""The Sunless Crypt — a small gamebook-style dungeon crawl, expressed as an
analint spec AND made playable by the generic runner in ``examples/play.py``.

This is an experiment (research/21): can a model authored purely for *checking*
also be *executed* as a real text game — text, choices, HP, inventory — without
touching framework code? Everything in this file except the ``NARRATION`` /
``describe`` data below is an ordinary verifiable analint model: the same spec is
checked by ``analint examples/sunless_crypt/`` and played by
``uv run python examples/play.py sunless_crypt``.

Critical path: take the torch → light it → grab the sword in the armory → enter
the crypt → slay the guardian (barehanded fights cost blood) → take its key →
unlock the vault → take the amulet → place it on the altar to escape. Stumbling
through the dark crypt and fighting unarmed drain stamina; at zero you die.
"""

from enum import StrEnum

from analint import (
    Action,
    AlwaysHolds,
    DeadActions,
    Entity,
    Expect,
    Field,
    Lifecycle,
    NoDeadEnd,
    Not,
    Reachable,
    Scenario,
    Set,
    Spec,
    Subtract,
    Transition,
)

# ── State ────────────────────────────────────────────────────────────────────────


class Room(StrEnum):
    ENTRANCE = "entrance"
    HALL = "hall"
    ARMORY = "armory"
    CRYPT = "crypt"
    VAULT = "vault"
    ALTAR = "altar"


class Result(StrEnum):
    PLAYING = "playing"
    ESCAPED = "escaped"
    DEAD = "dead"


class Hero(Entity):
    location: Room = Room.ENTRANCE
    stamina: int = Field(5, ge=0, le=5, saturate=True)  # 0 = death; clamps, never negative
    has_torch: bool = False
    torch_lit: bool = False
    has_sword: bool = False
    has_key: bool = False
    has_amulet: bool = False


class Crypt(Entity):
    guardian_alive: bool = True
    vault_open: bool = False


class Game(Entity):
    result: Result = Lifecycle(
        initial=Result.PLAYING,
        transitions=[Transition(Result.PLAYING, [Result.ESCAPED, Result.DEAD])],
        terminal=[Result.ESCAPED, Result.DEAD],
    )


# ── Movement ───────────────────────────────────────────────────────────────────

enter_hall = Action(
    name="Go deeper into the hall",
    pre=[Hero.location == Room.ENTRANCE],
    effect=[Set(Hero.location, Room.HALL)],
)
back_to_entrance = Action(
    name="Return to the entrance",
    pre=[Hero.location == Room.HALL],
    effect=[Set(Hero.location, Room.ENTRANCE)],
)
enter_armory = Action(
    name="Step into the armory",
    pre=[Hero.location == Room.HALL],
    effect=[Set(Hero.location, Room.ARMORY)],
)
leave_armory = Action(
    name="Back to the hall",
    pre=[Hero.location == Room.ARMORY],
    effect=[Set(Hero.location, Room.HALL)],
)
enter_crypt_lit = Action(
    name="Enter the crypt (torch held high)",
    pre=[Hero.location == Room.HALL, Hero.torch_lit],
    effect=[Set(Hero.location, Room.CRYPT)],
)
enter_crypt_dark = Action(
    name="Grope into the pitch-dark crypt",
    pre=[Hero.location == Room.HALL, Not(Hero.torch_lit)],
    effect=[Set(Hero.location, Room.CRYPT), Subtract(Hero.stamina, 1)],
)
leave_crypt = Action(
    name="Back to the hall",
    pre=[Hero.location == Room.CRYPT],
    effect=[Set(Hero.location, Room.HALL)],
)
enter_altar = Action(
    name="Approach the altar",
    pre=[Hero.location == Room.HALL],
    effect=[Set(Hero.location, Room.ALTAR)],
)
leave_altar = Action(
    name="Back to the hall",
    pre=[Hero.location == Room.ALTAR],
    effect=[Set(Hero.location, Room.HALL)],
)
enter_vault = Action(
    name="Enter the open vault",
    pre=[Hero.location == Room.CRYPT, Crypt.vault_open],
    effect=[Set(Hero.location, Room.VAULT)],
)
leave_vault = Action(
    name="Back to the crypt",
    pre=[Hero.location == Room.VAULT],
    effect=[Set(Hero.location, Room.CRYPT)],
)

# ── Items & deeds ──────────────────────────────────────────────────────────────

take_torch = Action(
    name="Take the guttering torch from its sconce",
    pre=[Hero.location == Room.ENTRANCE, Not(Hero.has_torch)],
    effect=[Set(Hero.has_torch, True)],
)
light_torch = Action(
    name="Light the torch",
    pre=[Hero.has_torch, Not(Hero.torch_lit)],
    effect=[Set(Hero.torch_lit, True)],
)
take_sword = Action(
    name="Pry the rusted sword from a dead hand",
    pre=[Hero.location == Room.ARMORY, Not(Hero.has_sword)],
    effect=[Set(Hero.has_sword, True)],
)
slay_guardian = Action(
    name="Cut the bone guardian down with your sword",
    pre=[
        Hero.location == Room.CRYPT,
        Crypt.guardian_alive,
        Hero.has_sword,
    ],
    effect=[Set(Crypt.guardian_alive, False)],
)
fight_barehanded = Action(
    name="Grapple the guardian with bare hands",
    pre=[
        Hero.location == Room.CRYPT,
        Crypt.guardian_alive,
        Not(Hero.has_sword),
    ],
    effect=[Subtract(Hero.stamina, 2)],  # it claws you; it does not fall
)
take_key = Action(
    name="Take the iron key from the guardian's ribs",
    pre=[
        Hero.location == Room.CRYPT,
        Not(Crypt.guardian_alive),
        Not(Hero.has_key),
    ],
    effect=[Set(Hero.has_key, True)],
)
unlock_vault = Action(
    name="Unlock the vault with the iron key",
    pre=[
        Hero.location == Room.CRYPT,
        Hero.has_key,
        Not(Crypt.vault_open),
    ],
    effect=[Set(Crypt.vault_open, True)],
)
take_amulet = Action(
    name="Lift the amulet from its pedestal",
    pre=[Hero.location == Room.VAULT, Not(Hero.has_amulet)],
    effect=[Set(Hero.has_amulet, True)],
)
place_amulet = Action(
    name="Set the amulet on the altar and escape",
    pre=[
        Hero.location == Room.ALTAR,
        Hero.has_amulet,
        Game.result == Result.PLAYING,
    ],
    effect=[Set(Game.result, Result.ESCAPED)],
)
succumb = Action(
    name="Collapse, drained of all blood",
    pre=[Hero.stamina == 0, Game.result == Result.PLAYING],
    effect=[Set(Game.result, Result.DEAD)],
)

# ── Verification queries (the model is also a checkable spec) ──────────────────

win_is_reachable = Reachable(Game.result == Result.ESCAPED, label="the crypt can be escaped")
death_is_reachable = Reachable(Game.result == Result.DEAD, label="the hero can die")
stamina_never_negative = AlwaysHolds(Hero.stamina >= 0, label="stamina never goes negative")
no_softlock = NoDeadEnd(goal=Game.result != Result.PLAYING, label="every run can reach an ending")
every_action_playable = DeadActions()

# ── A few scenarios (concrete examples / regression coverage) ──────────────────

sc_take_torch = Scenario(
    name="Take the torch at the entrance",
    action=take_torch,
    given=[Hero()],
    then=[Hero.has_torch],
)
sc_dark_hurts = Scenario(
    name="Groping into the dark crypt costs stamina",
    action=enter_crypt_dark,
    given=[Hero(location=Room.HALL, stamina=5, torch_lit=False)],
    then=[Hero.stamina == 4, Hero.location == Room.CRYPT],
)
sc_barehanded_bleeds = Scenario(
    name="Fighting the guardian unarmed drains two stamina",
    action=fight_barehanded,
    given=[Hero(location=Room.CRYPT, stamina=5, has_sword=False), Crypt(guardian_alive=True)],
    then=[Hero.stamina == 3],
)
sc_slay = Scenario(
    name="The sword fells the guardian",
    action=slay_guardian,
    given=[Hero(location=Room.CRYPT, has_sword=True), Crypt(guardian_alive=True)],
    then=[Not(Crypt.guardian_alive)],
)
sc_key_needs_dead_guardian = Scenario(
    name="The key cannot be taken while the guardian stands",
    action=take_key,
    given=[Hero(location=Room.CRYPT), Crypt(guardian_alive=True)],
    expected=Expect.FAIL,
)
sc_vault_needs_key = Scenario(
    name="The vault will not open without the key",
    action=unlock_vault,
    given=[Hero(location=Room.CRYPT, has_key=False), Crypt(guardian_alive=False)],
    expected=Expect.FAIL,
)
sc_escape = Scenario(
    name="The amulet on the altar wins the game",
    action=place_amulet,
    given=[Hero(location=Room.ALTAR, has_amulet=True), Game()],
    then=[Game.result == Result.ESCAPED],
)
sc_death = Scenario(
    name="At zero stamina the hero collapses",
    action=succumb,
    given=[Hero(stamina=0), Game()],
    then=[Game.result == Result.DEAD],
)
sc_no_act_when_dead = Scenario(
    name="A finished game accepts no more deeds",
    action=place_amulet,
    given=[Hero(location=Room.ALTAR, has_amulet=True), Game(result=Result.DEAD)],
    expected=Expect.FAIL,
)

spec = Spec(
    id="sunless-crypt",
    name="The Sunless Crypt",
    version="1.0.0",
    description="A gamebook dungeon crawl that is both checked and played from one model",
)


# ── Narration — plain Python data beside the model, NOT part of the framework ──
# This is the experiment's whole point: mechanics live in the model; prose does
# not. The generic runner asks the game module to narrate the current state.

_ROOMS = {
    Room.ENTRANCE: "A cold archway. A guttering torch sits in a wall sconce.",
    Room.HALL: "A vaulted hall. Passages lead to an armory, a crypt, and an altar.",
    Room.ARMORY: "Racks of rotten gear. One rusted sword juts from a skeleton's grip.",
    Room.CRYPT: "A low crypt that reeks of old death. A heavy vault door stands to one side.",
    Room.VAULT: "The vault. On a pedestal rests a faintly glowing amulet.",
    Room.ALTAR: "A black stone altar, scored with a hollow the size of an amulet.",
}


def describe(ctx) -> str:
    """Narrate the current state. Reads model state, returns prose."""
    hero = ctx[Hero]
    crypt = ctx[Crypt]
    lines = [_ROOMS[hero.location]]
    if hero.location == Room.CRYPT and crypt.guardian_alive:
        lines.append("A bone guardian rises between you and the vault.")
    if hero.location == Room.CRYPT and not hero.torch_lit:
        lines.append("It is utterly dark; you feel your way by the cold walls.")
    carried = [
        name
        for flag, name in [
            (hero.has_torch, "torch" + (" (lit)" if hero.torch_lit else "")),
            (hero.has_sword, "sword"),
            (hero.has_key, "iron key"),
            (hero.has_amulet, "amulet"),
        ]
        if flag
    ]
    lines.append(f"Stamina {hero.stamina}/5 · Carrying: {', '.join(carried) or 'nothing'}")
    return "\n".join(lines)


INTRO = "THE SUNLESS CRYPT\nYou descend for the amulet. Few return.\n"
ENDINGS = {
    Result.ESCAPED: "The amulet flares; the crypt releases you. YOU ESCAPED.",
    Result.DEAD: "Your strength fails in the dark. YOU DIED.",
}
# Forced transitions the runner fires automatically when enabled (no real choice).
AUTO = {"succumb"}
