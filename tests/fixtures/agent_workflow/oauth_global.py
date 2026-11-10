from oauth.protocol import TokenState, tokens

from analint import Bound, Count, Invariant

wf_token = Bound("wf_token", tokens)
global_single_active_token = Invariant(Count(wf_token, wf_token.state == TokenState.ACTIVE) <= 1)
