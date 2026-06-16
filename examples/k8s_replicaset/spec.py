"""Kubernetes ReplicaSet + ResourceQuota — the P4.5 project-sized dogfood
(research/26 §P4.5). A real, externally documented system, modelled in a
deliberately narrow slice so its important guarantees stay *safety / reachability*
— never liveness.

What we DELIBERATELY do not model (research/25 boundary): "the ReplicaSet
eventually converges". That is a liveness/fairness claim and analint is bounded
reachability only. We model instead: a converged state is *reachable* when the
quota permits, the quota is *never* exceeded, under-replication caused by the
quota is *reachable*, and recovery (quota raised / pods deleted) makes a converged
state *reachable again* (a no-dead-end question), not inevitable.

Scope (kept small for exhaustive BFS): 1 namespace, 1 count/pods ResourceQuota,
1 ReplicaSet, 3 Pod slots. Omitted: Deployment rollouts, scheduler/nodes,
readiness, CPU/memory requests, multiple namespaces. (The second ReplicaSet,
orphan acquisition and bare pods arrive as later steps of the change series.)
"""

from enum import StrEnum

from analint import (
    Absent,
    Action,
    Add,
    AlwaysHolds,
    And,
    Bound,
    Count,
    Create,
    Delete,
    Entity,
    Field,
    Initial,
    NoDeadEnd,
    Param,
    Present,
    Reachable,
    Scope,
    Spec,
    Subtract,
)

MAX_PODS = 3


class Owner(StrEnum):
    RS = "replicaset"  # owned by the ReplicaSet (its ownerReference)
    NONE = "none"  # an orphan / bare pod (no controller owner)


class Namespace(Entity):
    quota: int = Field(MAX_PODS, ge=0, le=MAX_PODS)  # the count/pods ResourceQuota


class ReplicaSet(Entity):
    desired: int = Field(0, ge=0, le=MAX_PODS)  # spec.replicas


class Pod(Entity):
    owner: Owner = Field(Owner.RS)  # ownerReference (set when the controller creates it)


pods = Scope(Pod, keys=["p0", "p1", "p2"])
pod = Bound("pod", pods)

# Live pods in the namespace, and those owned by the ReplicaSet.
live_pods = Count(pod, Present(pod))
owned_pods = Count(pod, And(Present(pod), pod.owner == Owner.RS))

is_converged = owned_pods == ReplicaSet.desired

# ── Actions ──────────────────────────────────────────────────────────────────────
slot = Param("slot", pods)

scale_up = Action(
    name="Raise the ReplicaSet's desired replica count",
    pre=[ReplicaSet.desired < MAX_PODS],
    effect=[Add(ReplicaSet.desired, 1)],
)

scale_down = Action(
    name="Lower the ReplicaSet's desired replica count",
    pre=[ReplicaSet.desired > 0],
    effect=[Subtract(ReplicaSet.desired, 1)],
)

reconcile_create = Action(
    name="The controller creates a Pod toward the desired count (if quota admits)",
    params=[slot],
    # below desired AND the namespace quota admits one more pod; Create rejects a
    # already-present slot, so no explicit absence guard is needed.
    pre=[owned_pods < ReplicaSet.desired, live_pods < Namespace.quota],
    effect=[Create(slot, owner=Owner.RS)],
)

reconcile_delete = Action(
    name="The controller deletes a surplus Pod it owns (above the desired count)",
    params=[slot],
    pre=[Present(slot), slot.owner == Owner.RS, owned_pods > ReplicaSet.desired],
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
    label="the live pod count never exceeds the ResourceQuota",
)

# NOTE: "owned never exceeds desired" is deliberately NOT a property — a scale-down
# leaves surplus owned pods until the controller deletes them (real k8s behaviour),
# so that transient over-replication is expected, not a violation. We instead show
# the surplus is always recoverable (converged_always_recoverable).

converged_is_reachable = Reachable(
    And(ReplicaSet.desired == MAX_PODS, is_converged),
    label="a fully converged state is reachable when the quota permits",
)

under_replicated_by_quota_is_reachable = Reachable(
    And(owned_pods < ReplicaSet.desired, live_pods == Namespace.quota),
    label="the quota can hold the ReplicaSet below its desired count",
)

# A no-dead-end question, NOT a liveness guarantee: from every reachable state a
# converged state can still be reached (recovery via quota raise / pod delete is
# always possible).
converged_always_recoverable = NoDeadEnd(
    goal=is_converged,
    label="a converged state remains reachable from every reachable state",
)


# The namespace starts EMPTY (no pods) — scope slots default to *present*, so the
# initial must mark them absent. `Initial` requires a `vary`, so we vary the
# starting quota over its domain (a natural multi-root: the namespace could begin
# with any pod limit) rather than add a degenerate clause; `desired` starts 0.
initial = Initial(
    vary=[Namespace.quota],
    given=[Absent(pods["p0"]), Absent(pods["p1"]), Absent(pods["p2"])],
)

spec = Spec(
    id="k8s_replicaset",
    name="Kubernetes ReplicaSet + count/pods ResourceQuota",
    version="0.1.0",
    description="A narrow, reachability-only slice: a ReplicaSet reconciles a Pod "
    "count under a namespace pod quota. Safety (quota never exceeded) and "
    "reachability (converged, quota-limited under-replication, recovery) — never "
    "eventual convergence (liveness).",
    initial=initial,
)
