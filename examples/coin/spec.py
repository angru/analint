"""The Coin contract — a translation of Quint's flagship tutorial into analint.

Original: https://github.com/informalsystems/quint/blob/main/examples/tutorials/coin.qnt
(Igor Konnov, Informal Systems, 2023 — itself a model of the Solidity
"subcurrency" example). A custom coin: the minter issues coins, holders send
them to each other, and the interesting property is that the *total supply*
can overflow even though every individual balance is range-checked — the
teaching moment of the Quint lesson, reproduced here.

Deliberate translation choices (the comparison is the point — research/15):
- Quint's `balances: Addr -> UInt` map → one bounded `Account` scope;
  Quint's parameterized `send(sender, receiver, amount)` → one parameterized
  analint Action over `Param` domains, expanded by the engine.
- Quint's `nondet amount = 0.to(MAX_UINT).oneOf()` → `Param("amount", ge=1, le=3)`
  (we explore explicitly, so the domain is small and finite).
- Quint's `totalSupply` fold over the map → a named arithmetic expression
  over the three bounded account refs.
- Quint's `require(sender == minter)` → encoded structurally: minting is a
  separate `mint` action, distinct from the holder-to-holder `send`.

This example is DELIBERATELY RED, like trollbridge: `supply_never_overflows`
fails with a counterexample trace — the same violation the Quint lesson
demonstrates with `quint run --invariant totalSupplyDoesNotOverflowInv`.
"""

from analint import (
    Action,
    AlwaysHolds,
    And,
    Bound,
    DeadActions,
    Entity,
    Expect,
    Field,
    ForAll,
    Param,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Sum,
)

# In Quint: MAX_UINT = 2^256 - 1, checked symbolically by Apalache.
# We explore explicitly, so the domain is small: a balance fits 0..5 coins.
MAX_BALANCE = 5
MAX_SUPPLY = MAX_BALANCE  # the supply is supposed to fit the same range


# ── State (Quint: `var balances: Addr -> UInt` over a fixed address set) ──────


class Account(Entity):
    coins: int = Field(0, ge=0, le=MAX_BALANCE)


accounts = Scope(Account, keys=["alice", "bob", "eve"])
alice = accounts["alice"]
bob = accounts["bob"]
eve = accounts["eve"]
account = Bound("account", accounts)


# Quint: val totalSupply = ADDR.fold(0, (sum, a) => sum + balances.get(a))
# A finite aggregate over the account scope — no denormalized counter needed.
total_supply = Sum(account, account.coins)


# ── Actions (Quint: parameterized mint/send + nondet step) ────────────────────
# `Param` is the analint counterpart of Quint's action parameters and
# `nondet x = oneOf(...)`: one declaration over finite domains, expanded by
# the engine into concrete bound actions.

receiver = Param("receiver", accounts)
src = Param("src", accounts)
dst = Param("dst", accounts)
amount = Param("amount", ge=1, le=3)

mint = Action(
    name="Minter issues coins to a holder",
    params=[receiver, amount],
    pre=[receiver.coins <= MAX_BALANCE - amount],  # require(isUInt(newBal))
    effect=[Set(receiver.coins, receiver.coins + amount)],
)

send = Action(
    name="A holder pays another holder",
    params=[src, dst, amount],
    where=[src != dst],  # Quint allows self-sends as no-ops; we skip them
    pre=[
        src.coins >= amount,  # require(not(amount > balances.get(sender)))
        dst.coins <= MAX_BALANCE - amount,  # require(isUInt(newReceiverBal))
    ],
    # canonical effect form: "the next value IS this expression" —
    # right-hand sides always read the pre-state
    effect=[
        Set(src.coins, src.coins - amount),
        Set(dst.coins, dst.coins + amount),
    ],
)


# ── Scenarios (Quint: `run …Test` blocks) ─────────────────────────────────────


def _world(alice: int = 0, bob: int = 0, eve: int = 0) -> list:
    return [
        accounts["alice"](coins=alice),
        accounts["bob"](coins=bob),
        accounts["eve"](coins=eve),
    ]


# Quint: run sendWithoutMintTest = init.then(send(minter, "bob", 5)).fail()
sc_send_without_mint = Scenario(
    name="Sending before any minting is rejected",
    action=send.bind(src=alice, dst=bob, amount=3),
    given=_world(),
    expected=Expect.FAIL,
)

# Quint: run mintSendTest = init.then(mint(minter, "bob", 10))
#            .then(send("bob", "eve", 4)) … assert(bob == 6, eve == 4)
# analint scenarios run a single action, so the post-mint state goes into
# `given` (scaled down: bob was minted 5, sends 2).
sc_mint_then_send = Scenario(
    name="A minted holder can pay another holder",
    action=send.bind(src=bob, dst=eve, amount=2),
    given=_world(bob=5),
    then=[
        bob.coins == 3,
        eve.coins == 2,
        total_supply == 5,  # transfers do not change the supply
    ],
)

sc_no_overdraft = Scenario(
    name="A holder cannot send more than the balance",
    action=send.bind(src=eve, dst=alice, amount=1),
    given=_world(bob=3),  # eve has nothing
    expected=Expect.FAIL,
)

sc_receiver_overflow_blocked = Scenario(
    name="A transfer into a full balance is rejected",
    action=send.bind(src=bob, dst=alice, amount=1),
    given=_world(alice=MAX_BALANCE, bob=1),
    expected=Expect.FAIL,
)

sc_minting_works = Scenario(
    name="The minter issues coins out of thin air",
    action=mint.bind(receiver=alice, amount=3),
    given=_world(),
    then=[alice.coins == 3, total_supply == 3],
)


# ── Properties (Quint: invariants + temporal) ─────────────────────────────────

# Quint: val balancesRangeInv = ADDR.forall(a => isUInt(balances.get(a)))
# Field already enforces this structurally, but the original theorem now also
# translates literally through a finite quantifier.
balances_stay_in_range = AlwaysHolds(
    ForAll(
        account,
        And(account.coins >= 0, account.coins <= MAX_BALANCE),
    ),
    label="every bounded account balance remains in range",
)

# Quint: temporal NoSupplyOverflow = always(totalSupplyDoesNotOverflowInv)
# — and the lesson's point: this property is VIOLABLE, because every balance
# is range-checked but nothing checks the sum. The engine finds the same
# counterexample `quint run` finds.
supply_never_overflows = AlwaysHolds(
    total_supply <= MAX_SUPPLY,
    label="the total supply fits the same range as a single balance",
)

everyone_can_get_paid = Reachable(
    eve.coins > 0,
    label="coins can actually reach a regular holder",
)

every_method_callable = DeadActions()


# ── Spec ───────────────────────────────────────────────────────────────────────

spec = Spec(
    id="coin",
    name="Coin (Quint tutorial translation)",
    version="1.0.0",
    description="Solidity subcurrency, translated from Quint's coin.qnt — "
    "deliberately red: the supply-overflow violation from the "
    "Quint lesson is reproduced with a trace",
)
