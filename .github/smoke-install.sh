#!/usr/bin/env bash
# Install the built wheel the way a user would and run their first commands.
set -euo pipefail

WHEEL=$(ls "$PWD"/dist/*.whl)
WORK=${RUNNER_TEMP:-$(mktemp -d)}
export UV_TOOL_DIR="$WORK/tools" UV_TOOL_BIN_DIR="$WORK/bin" PATH="$WORK/bin:$PATH" NO_COLOR=1

uv tool install "$WHEEL"
litschema --version

cd "$WORK"
litschema init smoke
cd smoke
litschema status

# doctor exits 1 on a runner with no agent CLI, which is only a warning here.
# Any failed check is not.
REPORT=$(litschema doctor || true)
echo "$REPORT"
grep -q "on PATH (" <<<"$REPORT"
grep -q "pinned to litschema" <<<"$REPORT"
if grep -q "\[FAIL\]" <<<"$REPORT"; then
  echo "doctor reported a failed check" >&2
  exit 1
fi
