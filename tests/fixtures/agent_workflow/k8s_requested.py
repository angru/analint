from analint_spec import (
    Namespace,
    Owner,
    Present,
    create_bare_pod,
    decrease_quota,
    live_pods,
    pods,
    reconcile_create,
    replicasets,
)

from analint import Absent, Expect, Reachable, Scenario

lower_quota_below_usage = Scenario(
    action=decrease_quota,
    given=[
        Namespace(quota=1),
        replicasets[Owner.RS0](desired=2),
        replicasets[Owner.RS1](),
        pods["p0"](owner=Owner.RS0),
    ],
    then=[Namespace.quota == 0, Present(pods["p0"])],
)
controller_creation_over_quota_blocked = Scenario(
    action=reconcile_create.bind(rs=replicasets[Owner.RS0], slot=pods["p1"]),
    given=[
        Namespace(quota=0),
        replicasets[Owner.RS0](desired=2),
        replicasets[Owner.RS1](),
        pods["p0"](owner=Owner.RS0),
        Absent(pods["p1"]),
    ],
    expected=Expect.FAIL,
)
bare_creation_over_quota_blocked = Scenario(
    action=create_bare_pod.bind(slot=pods["p1"]),
    given=[
        Namespace(quota=0),
        replicasets[Owner.RS0](),
        replicasets[Owner.RS1](),
        pods["p0"](owner=Owner.NONE),
        Absent(pods["p1"]),
    ],
    expected=Expect.FAIL,
)
quota_below_usage_is_reachable = Reachable(live_pods > Namespace.quota)
