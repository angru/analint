#!/bin/sh
# Place the task diff for a read-only reviewer: .cache/review/{change.diff,paths.txt,identity.txt}.
set -eu
BASE=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)
HEAD_SHA=$(git rev-parse HEAD)
[ "$BASE" != "$HEAD_SHA" ] || { echo "no commits to review" >&2; exit 1; }
mkdir -p .cache/review
git diff "$BASE" "$HEAD_SHA" > .cache/review/change.diff
git diff --name-only "$BASE" "$HEAD_SHA" > .cache/review/paths.txt
printf 'base %s\nhead %s\n' "$BASE" "$HEAD_SHA" > .cache/review/identity.txt
printf '{"base": "%s", "headSha": "%s"}\n' "$BASE" "$HEAD_SHA"
