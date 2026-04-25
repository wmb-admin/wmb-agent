#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"

if [[ -z "$MODE" ]]; then
  echo "Usage: $0 <dev|hq|status>"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: env file not found: $ENV_FILE"
  exit 1
fi

get_value() {
  local key="$1"
  awk -F= -v k="$key" '$1==k {print substr($0, index($0, "=")+1); exit}' "$ENV_FILE"
}

upsert_value() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { done=0 }
    $0 ~ ("^" k "=") { print k "=" v; done=1; next }
    { print }
    END { if (!done) print k "=" v }
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

DEV_MODEL="$(get_value MODEL_NAME_DEV)"
HQ_MODEL="$(get_value MODEL_NAME_HQ)"

if [[ -z "$DEV_MODEL" ]]; then
  DEV_MODEL="deepseek-coder-v2:16b"
fi
if [[ -z "$HQ_MODEL" ]]; then
  HQ_MODEL="qwen3.6:35b"
fi

case "$MODE" in
  dev)
    upsert_value "MODEL_MODE" "dev"
    upsert_value "MODEL_NAME" "$DEV_MODEL"
    echo "Switched to DEV mode: MODEL_NAME=$DEV_MODEL"
    ;;
  hq)
    upsert_value "MODEL_MODE" "hq"
    upsert_value "MODEL_NAME" "$HQ_MODEL"
    echo "Switched to HQ mode: MODEL_NAME=$HQ_MODEL"
    ;;
  status)
    echo "ENV_FILE=$ENV_FILE"
    echo "MODEL_MODE=$(get_value MODEL_MODE)"
    echo "MODEL_NAME=$(get_value MODEL_NAME)"
    echo "MODEL_NAME_DEV=$DEV_MODEL"
    echo "MODEL_NAME_HQ=$HQ_MODEL"
    ;;
  *)
    echo "ERROR: unknown mode '$MODE'. Use dev | hq | status"
    exit 1
    ;;
esac
