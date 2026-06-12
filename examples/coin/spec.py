"""The Coin contract — a translation of Quint's flagship tutorial into analint.

Original: https://github.com/informalsystems/quint/blob/main/examples/tutorials/coin.qnt
(Igor Konnov, Informal Systems, 2023 — itself a model of the Solidity
"subcurrency" example). A custom coin: the minter issues coins, holders send
them to each other, and the interesting property is that the *total supply*
can overflow even though every individual balance is range-checked — the
teaching moment of the Quint lesson, reproduced here.

Deliberate translation choices (the comparison is the point — research/15):
- Quint's `balances: Addr -> UInt` map → three fixed account entities.
  analint has no collections: one parameterized Quint action `send(sender,
  receiver, amount)` becomes 6 concrete actions, built by a factory.
- Quint's `nondet amount = 0.to(MAX_UINT).oneOf()` → a unit denomination
  (every transfer moves 1 coin). Same state space shape, smaller.
- Quint's `totalSupply` fold over the map → a denormalized Ledger counter
  (analint has no arithmetic aggregates — yet).
- Quint's `require(sender == minter)` → encoded structurally: only the
  mint_to_* actions exist, and they carry `by=Minter`.

This example is DELIBERATELY RED, like trollbridge: `supply_never_overflows`
fails with a counterexample trace — the same violation the Quint lesson
demonstrates with `quint run --invariant totalSupplyDoesNotOverflowInv`.
"""

from analint import (
    Action,
    Actor,
    Add,
    AlwaysHolds,
    Assert,
    DeadActions,
    Entity,
    Expect,
    Field,
    Reachable,
    Scenario,
    Spec,
    Subtract,
)

# In Quint: MAX_UINT = 2^256 - 1, checked symbolically by Apalache.
# We explore explicitly, so the domain is small: a balance fits 0..5 coins.
MAX_BALANCE = 5
MAX_SUPPLY = MAX_BALANCE  # the supply is supposed to fit the same range


# ── Actors (Quint encodes msg.sender as an action parameter) ──────────────────


class Minter(Actor):
    """The contract creator — the only address allowed to mint."""


class Holder(Actor):
    """Any coin holder — can send coins it owns."""


# ── State (Quint: `var balances: Addr -> UInt` over a fixed address set) ──────


class AliceCoins(Entity):
    coins: int = Field(0, ge=0, le=MAX_BALANCE)


class BobCoins(Entity):
    coins: int = Field(0, ge=0, le=MAX_BALANCE)


class EveCoins(Entity):
    coins: int = Field(0, ge=0, le=MAX_BALANCE)


class Ledger(Entity):
    # Denormalized: Quint computes totalSupply as a fold over the balances
    # map; analint has no aggregates, so every mint maintains the counter.
    # The bound is deliberately wider than MAX_SUPPLY — the overflow must be
    # representable for the engine to find it.
    total_supply: int = Field(0, ge=0, le=3 * MAX_BALANCE)


_ACCOUNTS = {"alice": AliceCoins, "bob": BobCoins, "eve": EveCoins}


# ── Actions (Quint: parameterized mint/send + nondet step) ────────────────────
# The factory is the host-language functional layer — it constructs ordinary
# analint nodes, mirroring Quint's `pure def` section.


def _mint(name: str, receiver: type) -> Action:
    return Action(
        id=f"mint_to_{name}",
        name=f"Minter issues 1 coin to {name}",
        by=Minter,
        pre=[receiver.coins < MAX_BALANCE],  # require(isUInt(newBal))
        effect=[Add(receiver.coins, 1), Add(Ledger.total_supply, 1)],
    )


def _send(src_name: str, src: type, dst_name: str, dst: type) -> Action:
    return Action(
        id=f"send_{src_name}_to_{dst_name}",
        name=f"{src_name} sends 1 coin to {dst_name}",
        by=Holder,
        pre=[
            src.coins >= 1,  # require(not(amount > balances.get(sender)))
            dst.coins < MAX_BALANCE,  # require(isUInt(newReceiverBal))
        ],
        effect=[Subtract(src.coins, 1), Add(dst.coins, 1)],
    )


mint_to_alice = _mint("alice", AliceCoins)
mint_to_bob = _mint("bob", BobCoins)
mint_to_eve = _mint("eve", EveCoins)

send_alice_to_bob = _send("alice", AliceCoins, "bob", BobCoins)
send_alice_to_eve = _send("alice", AliceCoins, "eve", EveCoins)
send_bob_to_alice = _send("bob", BobCoins, "alice", AliceCoins)
send_bob_to_eve = _send("bob", BobCoins, "eve", EveCoins)
send_eve_to_alice = _send("eve", EveCoins, "alice", AliceCoins)
send_eve_to_bob = _send("eve", EveCoins, "bob", BobCoins)


# ── Scenarios (Quint: `run …Test` blocks) ─────────────────────────────────────


def _world(alice: int = 0, bob: int = 0, eve: int = 0) -> list:
    return [
        AliceCoins(coins=alice),
        BobCoins(coins=bob),
        EveCoins(coins=eve),
        Ledger(total_supply=alice + bob + eve),
    ]


# Quint: run sendWithoutMintTest = init.then(send(minter, "bob", 5)).fail()
sc_send_without_mint = Scenario(
    name="Sending before any minting is rejected",
    action=send_alice_to_bob,
    given=_world(),
    expected=Expect.FAIL,
)

# Quint: run mintSendTest = init.then(mint(minter, "bob", 10))
#            .then(send("bob", "eve", 4)) … assert(bob == 6, eve == 4)
# analint scenarios run a single action, so the post-mint state goes into
# `given` (scaled to the unit denomination: bob has 2, sends 1).
sc_mint_then_send = Scenario(
    name="A minted holder can pay another holder",
    action=send_bob_to_eve,
    given=_world(bob=2),
    then=[
        Assert(BobCoins.coins == 1),
        Assert(EveCoins.coins == 1),
        Assert(Ledger.total_supply == 2),  # transfers do not change the supply
    ],
)

sc_no_overdraft = Scenario(
    name="A holder cannot send more than the balance",
    action=send_eve_to_alice,
    given=_world(bob=3),  # eve has nothing
    expected=Expect.FAIL,
)

sc_receiver_overflow_blocked = Scenario(
    name="A transfer into a full balance is rejected",
    action=send_bob_to_alice,
    given=_world(alice=MAX_BALANCE, bob=1),
    expected=Expect.FAIL,
)


# ── Properties (Quint: invariants + temporal) ─────────────────────────────────

# Quint: val balancesRangeInv = ADDR.forall(a => isUInt(balances.get(a)))
# In analint this is not a separate invariant: Field(ge=0, le=MAX_BALANCE)
# already enforces the range at construction, in every scenario post-state,
# and as the engine's bounds.

# Quint: temporal NoSupplyOverflow = always(totalSupplyDoesNotOverflowInv)
# — and the lesson's point: this property is VIOLABLE, because every balance
# is range-checked but nothing checks the sum. The engine finds the same
# counterexample `quint run` finds.
supply_never_overflows = AlwaysHolds(
    Ledger.total_supply <= MAX_SUPPLY,
    label="the total supply fits the same range as a single balance",
)

everyone_can_get_paid = Reachable(
    EveCoins.coins > 0,
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
