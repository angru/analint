# k8s_replicaset — Kubernetes ReplicaSet + ResourceQuota (P4.5 dogfood)

## Purpose & source
The project-sized dogfood for the P4 workbench (research/26 §P4.5): a real,
externally documented system — Kubernetes ReplicaSets reconciling Pods under a
namespace `count/pods` ResourceQuota
([ReplicaSet](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/),
[ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)).
Chosen because its important guarantees are *safety / reachability*; its headline
"eventually converges" is **liveness** — deliberately out of scope (research/25).
It exercises multiplicity, presence (`Create`/`Delete`), `Count` aggregates and
`ownerReference` provenance together.

## Modeled scope & omissions
1 namespace, 1 count/pods ResourceQuota, **two ReplicaSets** competing for it, 3
Pod slots, **bare (unowned) pods** that also consume the quota, and **orphan
acquisition** (a controller adopts a matching unowned pod). Deliberately omitted:
Deployment rollouts, scheduler/nodes, readiness probes, CPU/memory requests,
multiple namespaces, and **eventual convergence** (liveness — analint is bounded
reachability only).

Abstractions: a quota decrease is modelled only down to current live usage (real
k8s allows lowering below usage and merely blocks new pods), so `live ≤ quota` is a
true invariant. "Owned never exceeds desired" is intentionally **not** a property —
a scale-down leaves a recoverable surplus until the controller deletes it (real
behaviour); we show that surplus is always recoverable instead.

## Key entities / actions / properties
- `Namespace` (quota), `ReplicaSet` scope (`Owner.RS0`/`Owner.RS1`, desired), `Pod` scope (present
  + `owner` ∈ RS0/RS1/NONE).
- Main uses unreleased `Key(rs)` for ownership and `initially_present=False`
  for the Pod scope. The parallel owner parameter/map and explicit canonical
  absent Pod snapshots are gone. Quota still varies over all four starting
  values; the normalized graph remains 1,792 states / 13,008 edges.
- `scale_up/down`, `reconcile_create/delete`, `acquire_orphan`,
  `create_bare_pod`/`delete_bare_pod`, `increase/decrease_quota`.
- `quota_never_exceeded` (AlwaysHolds); `both_converged_is_reachable`,
  `quota_can_starve_a_replicaset` (one RS's pods starve the other),
  `bare_pods_can_starve_a_replicaset` (Reachable);
  `rs0_converged_always_recoverable` (NoDeadEnd — recovery, not liveness);
  `every_action_usable` (DeadActions). Nine scenarios + two flows document it.

## Run
```
uv run analint check examples/k8s_replicaset
uv run analint explore examples/k8s_replicaset
uv run analint trace bare_pods_can_starve_a_replicaset -p examples/k8s_replicaset
```

## Expected outcome
PASS, exit 0, no warnings. ~1792 reachable states / ~13 008 edges, multi-root
exploration (the namespace may start with any quota 0..3).

## What a behavioural change means
If `quota_never_exceeded` fails, admission stopped respecting the quota; if
`rs0_converged_always_recoverable` fails, some state can no longer reach a
converged count (a genuine dead end). The measured requirement-change series and
the workbench-on-itself run (affects/explore/trace) are in research/28.

## Related research
research/26 §P4.5 (dogfood gate), research/28 (series + findings), research/25
(why liveness is out of scope).
