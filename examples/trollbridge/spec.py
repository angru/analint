# ruff: noqa: E712  (DSL: `== True/False` builds a Predicate; see research/27)
"""Troll Bridge — a deliberately broken micro-RPG.

The economy hides a softlock and the bridge hides a death the author forgot
to model. Scenarios all pass — these bugs are invisible to example-based
testing, because nobody writes a test for a situation they didn't think of.
The reachability queries find both, with traces.

Rules: the hero has 10 HP and 6 gold. The shop sells a sword (5 gold) and
potions (3 gold, +4 HP when drunk). The troll guarding the bridge can only
be slain with the sword (3 HP). Crossing the ruined bridge costs 8 HP.
"""

from analint import (
    Action,
    Add,
    AlwaysHolds,
    Assert,
    DeadActions,
    Entity,
    Expect,
    Invariant,
    NoDeadEnd,
    Reachable,
    Scenario,
    Set,
    Spec,
    Subtract,
    Unreachable,
)

# ── State ──────────────────────────────────────────────────────────────────────


class Hero(Entity):
    hp: int = 10
    gold: int = 6
    has_sword: bool = False
    potions: int = 0


class Troll(Entity):
    alive: bool = True


class Quest(Entity):
    bridge_crossed: bool = False


# ── Constraints ────────────────────────────────────────────────────────────────

hero_alive = Hero.hp > 0

gold_not_negative = Invariant(Hero.gold >= 0, label="Gold can not go negative")

# ── Actions ────────────────────────────────────────────────────────────────────

buy_sword = Action(
    pre=[hero_alive, Hero.gold >= 5, Hero.has_sword == False],
    effect=[Subtract(Hero.gold, 5), Set(Hero.has_sword, True)],
)

buy_potion = Action(
    pre=[hero_alive, Hero.gold >= 3],
    effect=[Subtract(Hero.gold, 3), Add(Hero.potions, 1)],
)

drink_potion = Action(
    pre=[hero_alive, Hero.potions >= 1],
    effect=[Subtract(Hero.potions, 1), Add(Hero.hp, 4)],
)

fight_troll = Action(
    pre=[hero_alive, Troll.alive == True, Hero.has_sword == True],
    effect=[Set(Troll.alive, False), Subtract(Hero.hp, 3)],
)

cross_bridge = Action(
    name="Cross the ruined bridge",
    pre=[hero_alive, Troll.alive == False],
    effect=[Set(Quest.bridge_crossed, True), Subtract(Hero.hp, 8)],
)

# ── Scenarios — all green, none of them sees the bugs ─────────────────────────

sc_buy_sword = Scenario(
    name="Sword purchase",
    action=buy_sword,
    given=[Hero(), Troll(), Quest()],
    then=[Assert(Hero.gold == 1), Assert(Hero.has_sword == True)],
)

sc_cannot_afford_sword = Scenario(
    name="No sword with 3 gold",
    action=buy_sword,
    given=[Hero(gold=3), Troll(), Quest()],
    expected=Expect.FAIL,
)

sc_potion = Scenario(
    name="Potion heals",
    action=drink_potion,
    given=[Hero(hp=7, potions=1), Troll(), Quest()],
    then=[Assert(Hero.hp == 11)],
)

sc_fight = Scenario(
    name="Armed hero slays the troll",
    action=fight_troll,
    given=[Hero(has_sword=True), Troll(), Quest()],
    then=[Assert(Troll.alive == False), Assert(Hero.hp == 7)],
)

sc_no_crossing_with_troll = Scenario(
    name="The troll blocks the bridge",
    action=cross_bridge,
    given=[Hero(), Troll(alive=True), Quest()],
    expected=Expect.FAIL,
)

sc_buy_two_potions = Scenario(
    name="Two potions fit the budget",
    action=buy_potion,
    given=[Hero(gold=3, potions=1), Troll(), Quest()],
    then=[Assert(Hero.gold == 0), Assert(Hero.potions == 2)],
)

# ── Queries — this is where the model breaks ──────────────────────────────────

bridge_is_reachable = Reachable(
    Quest.bridge_crossed == True,
    label="the quest can be completed",
)

# FAILS: buy_potion once → 3 gold left, the sword (5) is forever unaffordable,
# the troll is immortal without it → the bridge is unreachable. A classic
# economy softlock; no scenario above even hints at it.
no_softlock = NoDeadEnd(
    goal=Quest.bridge_crossed == True,
    label="the player can never spend themselves into a corner",
)

# FAILS: buy_sword → fight (10−3=7) → cross the ruined bridge (7−8=−1).
# The author forgot to require enough HP before crossing — or to model death.
hp_never_negative = AlwaysHolds(
    Hero.hp >= 0,
    label="the hero can not have negative health",
)

# PASSES: a regression guard — gold appears from nowhere in no reachable state.
no_gold_from_thin_air = Unreachable(
    Hero.gold > 6,
    label="gold can not exceed the starting purse",
)

every_action_playable = DeadActions()

# ── Spec ───────────────────────────────────────────────────────────────────────

spec = Spec(
    id="trollbridge",
    name="Troll Bridge",
    version="1.0.0",
    description="Deliberately broken micro-RPG: the engine finds a softlock "
    "and an unmodelled death that scenarios cannot see",
)
