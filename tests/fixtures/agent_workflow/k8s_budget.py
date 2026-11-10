from analint_spec import Namespace, live_pods

from analint import And, Reachable

three_pods_at_zero_quota = Reachable(And(live_pods == 3, Namespace.quota == 0), max_states=10000)
