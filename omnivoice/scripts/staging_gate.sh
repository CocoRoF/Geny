#!/usr/bin/env bash
#
# Staging-GPU regression gate for OmniVoice perf cycles.
#
# Run AFTER the omnivoice container is started and before merging any
# Tier-A PR. The gate exits non-zero on any of the following:
#   * /health never reaches phase=ok within $HEALTH_TIMEOUT seconds.
#   * compare_audio reports any case outside --atol.
#   * check_memory_residency reports any deviation (allocated/reserved
#     delta != 0, alloc retries, OOMs, fragmentation > 5%).
#
# Inputs (env vars):
#   API_URL              default http://localhost:9881
#   BASELINE_DIR         REQUIRED — directory holding *.npz baselines
#   BENCH_TEXTS          default scripts/texts_smoke.txt
#   VOICE                default "" (auto)
#   ATOL                 default 1e-4
#   BENCH_RUNS           default 3
#   BENCH_WARMUP         default 1
#   REPORT_DIR           default /tmp/omnivoice_gate
#   HEALTH_TIMEOUT       default 180
#
# Outputs:
#   $REPORT_DIR/{compare.json,bench.json,mem_before.json,mem_after.json,residency.json}

set -euo pipefail

API_URL="${API_URL:-http://localhost:9881}"
BASELINE_DIR="${BASELINE_DIR:?BASELINE_DIR is required}"
BENCH_TEXTS="${BENCH_TEXTS:-scripts/texts_smoke.txt}"
VOICE="${VOICE:-}"
ATOL="${ATOL:-1e-4}"
BENCH_RUNS="${BENCH_RUNS:-3}"
BENCH_WARMUP="${BENCH_WARMUP:-1}"
REPORT_DIR="${REPORT_DIR:-/tmp/omnivoice_gate}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
LABEL="${LABEL:-staging-gate}"

mkdir -p "$REPORT_DIR"

echo "[gate] waiting for ${API_URL}/health phase=ok (timeout ${HEALTH_TIMEOUT}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
while : ; do
  body="$(curl -fsS "${API_URL}/health" || true)"
  phase="$(printf '%s' "$body" | python -c 'import json,sys
try:
    d=json.load(sys.stdin); print(d.get("phase") or d.get("status") or "")
except Exception:
    print("")' || true)"
  if [[ "$phase" == "ok" ]]; then
    echo "[gate] /health reports phase=ok"
    break
  fi
  if (( $(date +%s) >= deadline )); then
    echo "[gate] FAIL — /health never reached phase=ok (last phase='${phase}')" >&2
    exit 4
  fi
  sleep 2
done

echo "[gate] capturing /diag/memory baseline -> ${REPORT_DIR}/mem_before.json"
curl -fsS "${API_URL}/diag/memory" -o "${REPORT_DIR}/mem_before.json" || {
  echo "[gate] FAIL — /diag/memory not reachable" >&2
  exit 5
}

VOICE_ARG=()
if [[ -n "$VOICE" ]]; then
  VOICE_ARG=(--voice "$VOICE")
fi

echo "[gate] running compare_audio check (atol=${ATOL})"
python -m server.compare_audio check \
  --api-url "$API_URL" \
  --baseline "$BASELINE_DIR" \
  --texts "$BENCH_TEXTS" \
  "${VOICE_ARG[@]}" \
  --atol "$ATOL" \
  --report "${REPORT_DIR}/compare.json"

echo "[gate] running bench (${BENCH_RUNS} runs, ${BENCH_WARMUP} warmup)"
python -m server.bench \
  --api-url "$API_URL" \
  --texts "$BENCH_TEXTS" \
  "${VOICE_ARG[@]}" \
  --runs "$BENCH_RUNS" \
  --warmup "$BENCH_WARMUP" \
  --label "$LABEL" \
  --json "${REPORT_DIR}/bench.json"

echo "[gate] capturing /diag/memory after-state -> ${REPORT_DIR}/mem_after.json"
curl -fsS "${API_URL}/diag/memory" -o "${REPORT_DIR}/mem_after.json"

echo "[gate] running check_memory_residency"
python scripts/check_memory_residency.py \
  "${REPORT_DIR}/mem_before.json" \
  "${REPORT_DIR}/mem_after.json" \
  --max-allocated-delta-bytes 0 \
  --max-reserved-delta-bytes 0 \
  --max-retries-delta 0 \
  --max-fragmentation 0.05 \
  --report "${REPORT_DIR}/residency.json"

echo "[gate] PASS — all checks succeeded. Reports under ${REPORT_DIR}"
