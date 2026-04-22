#!/usr/bin/env bash
#
# Convenience wrapper around `python -m server.bench` with sane
# defaults for staging GPU runs. Writes JSON to /tmp/bench_<label>.json
# and emits the markdown row to stdout so the operator can paste it
# into benchmarks.md.

set -euo pipefail

API_URL="${API_URL:-http://localhost:9881}"
TEXTS="${TEXTS:-scripts/texts_smoke.txt}"
RUNS="${RUNS:-3}"
WARMUP="${WARMUP:-1}"
LABEL="${LABEL:-bench}"
VOICE="${VOICE:-}"
OUT="${OUT:-/tmp/bench_${LABEL}.json}"

VOICE_ARG=()
if [[ -n "$VOICE" ]]; then
  VOICE_ARG=(--voice "$VOICE")
fi

python -m server.bench \
  --api-url "$API_URL" \
  --texts "$TEXTS" \
  "${VOICE_ARG[@]}" \
  --runs "$RUNS" \
  --warmup "$WARMUP" \
  --label "$LABEL" \
  --json "$OUT"

echo
echo "── markdown row ──"
python -m scripts.bench_to_md --json "$OUT" --label "$LABEL"
