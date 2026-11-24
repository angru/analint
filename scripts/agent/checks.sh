#!/bin/sh
# Repository checks for an agent task run. Always exits 0 and reports the result as JSON, so a
# failure goes back to the implementer through the review loop instead of ending the run.
# Prints {"passed": bool, "tail": "<last lines of output>"}.
OUT=$(mktemp)
if uv run --frozen pytest -q >"$OUT" 2>&1; then
  printf '{"passed": true, "tail": ""}\n'
else
  # JSON-escape the last 30 lines with shell tools only (no Python in the sandbox).
  TAIL=$(tail -n 30 "$OUT" | cut -c1-240 | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\t' ' ' | awk 'BEGIN{ORS="\\n"} {print}')
  printf '{"passed": false, "tail": "%s"}\n' "$TAIL"
fi
rm -f "$OUT"
exit 0
