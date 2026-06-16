# k8s_replicaset — Kubernetes ReplicaSet + ResourceQuota (P4.5 dogfood)

## Purpose & source
The project-sized dogfood for the P4 workbench (research/26 §P4.5): a real,
externally documented system — a Kubernetes ReplicaSet reconciling a Pod count
under a namespace `count/pods` ResourceQuota
([ReplicaSet](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/),
[ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)).
Chosen because its important guarantees are *safety / reachability*, and its
headline "eventually converges" is **liveness** — deliberately out of scope
(research/25). It exercises multiplicity, presence (`Create`/`Delete`), `Count`
aggregates and provenance (`ownerReference`) together.

## Modeled scope & omissions
1 namespace, 1 count/pods ResourceQuota, 1 ReplicaSet, 3 Pod slots (the second
ReplicaSet, orphan acquisition and bare pods are later steps of the change
series). Deliberately omitted: Deployment rollouts, scheduler/nodes, readiness
probes, CPU/memory requests, multiple namespaces, and **eventual convergence**
(liveness/fairness — analint is bounded reachability only).

Abstraction: a quota decrease is modelled only down to current live usage (real
k8s allows lowering below usage and merely blocks new pods), so `live ≤ quota` is
a true invariant. "Owned never exceeds desired" is intentionally **not** a
property — a scale-down leaves surplus owned pods until the controller deletes
them (real behaviour); we show that surplus is always recoverable instead.

## Key entities / actions / properties
- `Namespace` (quota), `ReplicaSet` (desired), `Pod` scope (present + `owner`).
- `scale_up/down`, `reconcile_create/delete` (controller, quota-admitted),
  `increase/decrease_quota`.
- `quota_never_exceeded` (AlwaysHolds), `converged_is_reachable` /
  `under_replicated_by_quota_is_reachable` (Reachable), and
  `converged_always_recoverable` (NoDeadEnd — a recovery question, not liveness).

## Run
```
uv run analint check examples/k8s_replicaset
uv run analint explore examples/k8s_replicaset
uv run analint trace under_replicated_by_quota_is_reachable -p examples/k8s_replicaset
```

## Expected outcome
PASS, exit 0, with **6 intentional `has no scenarios` warnings** (one per action;
the queries verify behaviour exhaustively across all reachable orders). Multi-root
exploration: the namespace may start with any quota 0..3.

## What a behavioural change means
If `quota_never_exceeded` fails, admission stopped respecting the quota; if
`converged_always_recoverable` fails, some state can no longer reach a converged
count (a genuine dead end). The measured requirement-change series lives in
research/26 §P4.5 / research/28.

## Related research
research/26 §P4.5 (dogfood gate), research/25 (why liveness is out of scope).
