#!/bin/sh
# Bind repository checks and independent review to the same clean commit.
set -eu
export GIT_OPTIONAL_LOCKS=0

fail() { echo "$*" >&2; exit 1; }

clean_head() {
    status=$(git status --porcelain --untracked-files=normal) || return 1
    [ -z "$status" ] || fail "review requires a clean checkout: $status"
    git rev-parse HEAD
}

case "$1" in
    baseline)
        head=$(clean_head)
        printf '{"baseSha":"%s"}\n' "$head"
        ;;
    verify)
        base=$2
        head=$3
        actual=$(clean_head)
        [ "$actual" = "$head" ] || fail "implementation SHA does not match HEAD"
        [ "$base" != "$head" ] || fail "no implementation commit"
        git merge-base --is-ancestor "$base" "$head" || fail "implementation is not based on the starting commit"

        uv run --frozen ruff check . >&2
        uv run --frozen ruff format --check . >&2
        uv run --frozen ty check >&2
        sh scripts/agent/checks.sh --strict >&2

        actual=$(clean_head)
        [ "$actual" = "$head" ] || fail "checkout moved during verification"
        sh scripts/agent/review-diff.sh "$base" "$head"
        ;;
    handoff)
        actual=$(clean_head)
        [ "$actual" = "$2" ] && [ "$2" = "$3" ] || fail "checked, reviewed and current SHAs must match"
        [ "$4" = proceed ] || fail "independent reviewer did not approve this SHA"
        printf '{"headSha":"%s"}\n' "$actual"
        ;;
    *) fail "expected baseline, verify or handoff" ;;
esac
