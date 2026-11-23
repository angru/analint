#!/bin/sh
# Full repository checks for an agent task run.
set -eu
uv run --frozen pytest -q >&2
printf '{"passed": true}\n'
