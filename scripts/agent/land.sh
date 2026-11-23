#!/bin/sh
# Land an owner-approved, reviewed head through a GitHub pull request (squash merge).
# The owner's local checkout is never touched; only remote-tracking refs are refreshed.
#   land.sh <head-sha> <task title>
set -eu
SHA="$1"; TITLE="${2:-Agent task}"
[ "$(git rev-parse HEAD)" = "$SHA" ] || { echo "checkout moved after review" >&2; exit 1; }
BRANCH="agent/$(printf '%s' "$SHA" | cut -c1-12)"
git push -q origin "$SHA:refs/heads/$BRANCH"
BODY=$(printf '%s\n\n%s\n' "Plan task from the assistant app: implemented, checked and independently reviewed by agents in a Worker Board task-run, then approved by the owner." "Opened by Worker Board \`task-run\`.")
URL=$(gh pr view "$BRANCH" --json url --jq .url 2>/dev/null || gh pr create --base main --head "$BRANCH" --title "$TITLE" --body "$BODY")
gh pr merge "$URL" --squash --delete-branch >&2
git fetch -q origin main
printf '{"merged": "%s"}\n' "$URL"
