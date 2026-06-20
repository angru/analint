"""Kubernetes ReplicaSet + ResourceQuota — the P4.5 project-sized dogfood
(research/26 §P4.5). A real, externally documented system, modelled in a
deliberately narrow slice so its important guarantees stay *safety / reachability*
— never liveness.

What we DELIBERATELY do not model (research/25 boundary): "the ReplicaSet
eventually converges". That is a liveness/fairness claim and analint is bounded
reachability only. We model instead: a converged state is *reachable* when the
quota permits, the quota is *never* exceeded, under-replication caused by quota
competition is *reachable*, and a converged state remains *reachable* from every
state (a no-dead-end question), not inevitable.

Scope (kept small for exhaustive BFS): 1 namespace, 1 count/pods ResourceQuota,
**two ReplicaSets** competing for it, 3 Pod slots, **bare (unowned) pods** that
also consume the quota, and **orphan acquisition** (a controller adopts a matching
unowned pod). Omitted: Deployment rollouts, scheduler/nodes, readiness, CPU/memory
requests, multiple namespaces. The measured change series is in research/28.
"""

from enum import StrEnum

from analint import (
    Absent,
    Action,
    Add,
    AlwaysHolds,
    And,
    Assert,
    Bound,
    Count,
    Create,
    DeadActions,
    Delete,
    Entity,
    Expect,
    Field,
    Flow,
    Implies,
    Initial,
    NoDeadEnd,
    Param,
    Present,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Subtract,
)

MAX_PODS = 3


class Owner(StrEnum):
    RS0 = "replicaset-0"  # ownerReference to ReplicaSet rs0
    RS1 = "replicaset-1"  # ownerReference to ReplicaSet rs1
    NONE = "none"  # an orphan / bare pod (no controller owner) — used in later steps


class Namespace(Entity):
    quota: int = Field(MAX_PODS, ge=0, le=MAX_PODS)  # the count/pods ResourceQuota


class ReplicaSet(Entity):
    desired: int = Field(0, ge=0, le=MAX_PODS)  # spec.replicas


replicasets = Scope(ReplicaSet, keys=["rs0", "rs1"])


class Pod(Entity):
    owner: Owner = Field(Owner.RS0)  # ownerReference (set when a controller creates it)


pods = Scope(Pod, keys=["p0", "p1", "p2"])
pod = Bound("pod", pods)

live_pods = Count(pod, Present(pod))


def owned(owner_value: object) -> Count:
    """Live pods carrying this owner — a literal Owner, or an action's owner param."""
    return Count(pod, And(Present(pod), pod.owner == owner_value))


# ── Actions ──────────────────────────────────────────────────────────────────────
rs = Param("rs", replicasets)
rs_owner = Param("rs_owner", Owner.RS0, Owner.RS1)
slot = Param("slot", pods)

# Statically tie each ReplicaSet slot to the ownerReference its pods carry.
_rs_is_owner = [
    Implies(rs == replicasets["rs0"], rs_owner == Owner.RS0),
    Implies(rs == replicasets["rs1"], rs_owner == Owner.RS1),
]

scale_up = Action(
    name="Raise a ReplicaSet's desired replica count",
    params=[rs],
    pre=[rs.desired < MAX_PODS],
    effect=[Add(rs.desired, 1)],
)

scale_down = Action(
    name="Lower a ReplicaSet's desired replica count",
    params=[rs],
    pre=[rs.desired > 0],
    effect=[Subtract(rs.desired, 1)],
)

reconcile_create = Action(
    name="A controller creates a Pod toward its desired count (if the quota admits)",
    params=[rs, rs_owner, slot],
    where=_rs_is_owner,
    # below this ReplicaSet's desired AND the shared namespace quota admits one more
    pre=[owned(rs_owner) < rs.desired, live_pods < Namespace.quota],
    effect=[Create(slot, owner=rs_owner)],
)

reconcile_delete = Action(
    name="A controller deletes a surplus Pod IT owns (never another ReplicaSet's)",
    params=[rs, rs_owner, slot],
    where=_rs_is_owner,
    pre=[Present(slot), slot.owner == rs_owner, owned(rs_owner) > rs.desired],
    effect=[Delete(slot)],
)

acquire_orphan = Action(
    name="A controller adopts a matching orphan/bare Pod toward its desired count",
    params=[rs, rs_owner, slot],
    where=_rs_is_owner,
    # an existing unowned pod is adopted (no new quota consumed) when below desired
    pre=[Present(slot), slot.owner == Owner.NONE, owned(rs_owner) < rs.desired],
    effect=[Set(slot.owner, rs_owner)],
)

create_bare_pod = Action(
    name="A user creates a bare Pod (no controller owner), consuming quota",
    params=[slot],
    pre=[live_pods < Namespace.quota],
    effect=[Create(slot, owner=Owner.NONE)],
)

delete_bare_pod = Action(
    name="A user deletes a bare Pod, freeing quota",
    params=[slot],
    pre=[Present(slot), slot.owner == Owner.NONE],
    effect=[Delete(slot)],
)

increase_quota = Action(
    name="Raise the ResourceQuota pod limit",
    pre=[Namespace.quota < MAX_PODS],
    effect=[Add(Namespace.quota, 1)],
)

decrease_quota = Action(
    name="Lower the ResourceQuota pod limit (not below current usage)",
    # Abstraction: real k8s lets a quota drop below live usage (it merely blocks
    # new pods); we model the admission-consistent variant where the limit never
    # drops below what is already live, so `live <= quota` is a true invariant.
    pre=[Namespace.quota > 0, Namespace.quota > live_pods],
    effect=[Subtract(Namespace.quota, 1)],
)


# ── Properties (reachability / safety only — no liveness) ─────────────────────────
quota_never_exceeded = AlwaysHolds(
    live_pods <= Namespace.quota,
    label="the live pod count never exceeds the shared ResourceQuota",
)

# NOTE: "owned never exceeds desired" is deliberately NOT a property — a scale-down
# leaves surplus owned pods until the controller deletes them (real k8s behaviour),
# so that transient over-replication is expected, not a violation.

both_converged_is_reachable = Reachable(
    And(
        replicasets["rs0"].desired == 1,
        replicasets["rs1"].desired == 1,
        owned(Owner.RS0) == 1,
        owned(Owner.RS1) == 1,
    ),
    label="both ReplicaSets can be converged at once when the quota fits their sum",
)

quota_can_starve_a_replicaset = Reachable(
    And(
        Namespace.quota > 0,  # a real, non-zero quota...
        replicasets["rs0"].desired >= 1,
        owned(Owner.RS0) < replicasets["rs0"].desired,
        owned(Owner.RS1) >= 1,  # ...fully consumed by the OTHER ReplicaSet
        live_pods == Namespace.quota,
    ),
    label="one ReplicaSet's pods can consume the quota and starve the other",
)

bare_pods_can_starve_a_replicaset = Reachable(
    And(
        owned(Owner.RS0) < replicasets["rs0"].desired,
        live_pods == Namespace.quota,
        owned(Owner.NONE) >= 1,
    ),
    label="bare (unowned) pods can consume the quota and starve a ReplicaSet",
)

# A no-dead-end question, NOT a liveness guarantee: rs0 can always reach its desired
# count again from any reachable state (freeing quota via scale-down / deletion is
# always possible).
rs0_converged_always_recoverable = NoDeadEnd(
    goal=owned(Owner.RS0) == replicasets["rs0"].desired,
    label="rs0 can reach its desired count from every reachable state",
)

every_action_usable = DeadActions(
    label="every action (including orphan acquisition) is reachable and usable",
)


# ── Scenarios & flows (executable documentation, one per action family) ───────────
_RS = [replicasets["rs0"](), replicasets["rs1"]()]

sc_scale_up = Scenario(
    name="Scaling a ReplicaSet up raises its desired count",
    action=scale_up.bind(rs=replicasets["rs0"]),
    given=[replicasets["rs0"](desired=0), replicasets["rs1"]()],
    then=[replicasets["rs0"].desired == 1],
)

sc_scale_down = Scenario(
    name="Scaling a ReplicaSet down lowers its desired count",
    action=scale_down.bind(rs=replicasets["rs0"]),
    given=[replicasets["rs0"](desired=2), replicasets["rs1"]()],
    then=[replicasets["rs0"].desired == 1],
)

sc_reconcile_delete = Scenario(
    name="The controller deletes a surplus owned Pod",
    action=reconcile_delete.bind(rs=replicasets["rs0"], rs_owner=Owner.RS0, slot=pods["p1"]),
    given=[
        replicasets["rs0"](desired=1),
        replicasets["rs1"](),
        pods["p0"](owner=Owner.RS0),
        pods["p1"](owner=Owner.RS0),
    ],
    then=[owned(Owner.RS0) == 1],
)

sc_create_beyond_quota_blocked = Scenario(
    name="Creating a Pod beyond the quota is blocked",
    action=reconcile_create.bind(rs=replicasets["rs0"], rs_owner=Owner.RS0, slot=pods["p1"]),
    given=[
        Namespace(quota=1),
        replicasets["rs0"](desired=2),
        replicasets["rs1"](),
        pods["p0"](owner=Owner.RS0),  # live=1 already fills the quota
        Absent(pods["p1"]),  # the slot the controller would create into
    ],
    expected=Expect.FAIL,
)

sc_acquire_orphan = Scenario(
    name="A controller adopts a matching orphan Pod",
    action=acquire_orphan.bind(rs=replicasets["rs0"], rs_owner=Owner.RS0, slot=pods["p0"]),
    given=[replicasets["rs0"](desired=1), replicasets["rs1"](), pods["p0"](owner=Owner.NONE)],
    then=[pods["p0"].owner == Owner.RS0],
)

sc_create_bare_pod = Scenario(
    name="A user creates a bare Pod under the quota",
    action=create_bare_pod.bind(slot=pods["p0"]),
    given=[Namespace(quota=1), *_RS, Absent(pods["p0"])],
    then=[Present(pods["p0"]), pods["p0"].owner == Owner.NONE],
)

sc_delete_bare_pod = Scenario(
    name="A user deletes a bare Pod, freeing quota",
    action=delete_bare_pod.bind(slot=pods["p0"]),
    given=[*_RS, pods["p0"](owner=Owner.NONE)],
    then=[live_pods == 0],
)

sc_increase_quota = Scenario(
    name="Raising the ResourceQuota",
    action=increase_quota,
    given=[Namespace(quota=1), *_RS],
    then=[Namespace.quota == 2],
)

sc_decrease_quota = Scenario(
    name="Lowering the ResourceQuota when usage allows",
    action=decrease_quota,
    given=[Namespace(quota=2), *_RS],
    then=[Namespace.quota == 1],
)

# A happy path: both ReplicaSets converge to one Pod each under a fitting quota.
flow_both_converge = Flow(
    given=[Namespace(quota=2), *_RS],
    steps=[
        scale_up.bind(rs=replicasets["rs0"]),
        reconcile_create.bind(rs=replicasets["rs0"], rs_owner=Owner.RS0, slot=pods["p0"]),
        scale_up.bind(rs=replicasets["rs1"]),
        reconcile_create.bind(rs=replicasets["rs1"], rs_owner=Owner.RS1, slot=pods["p1"]),
        Assert(owned(Owner.RS0) == 1),
        Assert(owned(Owner.RS1) == 1),
    ],
)

# Starvation then recovery: a bare Pod holds the only quota slot; once deleted, the
# controller can create the owned Pod it wanted.
flow_starve_then_recover = Flow(
    given=[Namespace(quota=1), *_RS],
    steps=[
        create_bare_pod.bind(slot=pods["p0"]),  # live=1=quota — no room for the controller
        scale_up.bind(rs=replicasets["rs0"]),
        Assert(live_pods == 1),
        delete_bare_pod.bind(slot=pods["p0"]),  # free the quota
        reconcile_create.bind(rs=replicasets["rs0"], rs_owner=Owner.RS0, slot=pods["p0"]),
        Assert(owned(Owner.RS0) == 1),
    ],
)


# The namespace starts EMPTY (no pods); scope slots default to *present*, so the
# initial marks them absent. `Initial` requires a `vary`, so the starting quota
# varies over its domain (a natural multi-root); both ReplicaSets start at desired 0.
initial = Initial(
    vary=[Namespace.quota],
    given=[Absent(pods["p0"]), Absent(pods["p1"]), Absent(pods["p2"])],
)

spec = Spec(
    id="k8s_replicaset",
    name="Kubernetes ReplicaSet + count/pods ResourceQuota",
    version="0.5.0",
    description="A narrow, reachability-only slice: two ReplicaSets reconcile Pod "
    "counts competing for one namespace pod quota. Safety (quota never exceeded) "
    "and reachability (both converged, quota-starvation, recovery) — never eventual "
    "convergence (liveness).",
    initial=initial,
)
