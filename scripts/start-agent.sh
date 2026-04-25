#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE_DEFAULT="${ENV_FILE:-$ROOT_DIR/.env}"
ENV_FILE_PATH="$ENV_FILE_DEFAULT"
MODE=""
PROFILE=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/start-agent.sh
  ./scripts/start-agent.sh dev
  ./scripts/start-agent.sh hq
  ./scripts/start-agent.sh --mode <dev|hq>
  ./scripts/start-agent.sh --profile <dev|hq|stable>
  ./scripts/start-agent.sh --env-file <path-to-env>

Notes:
  - legacy mode 参数 (dev/hq) 会基于目标 env 文件切换 MODEL_MODE/MODEL_NAME。
  - profile 会直接使用预置配置文件，不再调用 switch-model-mode。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    dev|hq)
      if [[ -n "$MODE" || -n "$PROFILE" ]]; then
        echo "ERROR: mode/profile 重复指定"
        usage
        exit 1
      fi
      MODE="$1"
      shift
      ;;
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --profile)
      PROFILE="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE_PATH="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown arg '$1'"
      usage
      exit 1
      ;;
  esac
done

if [[ -n "$PROFILE" ]]; then
  case "$PROFILE" in
    dev|hq|stable) ;;
    *)
      echo "ERROR: unsupported profile '$PROFILE' (allowed: dev|hq|stable)"
      exit 1
      ;;
  esac
  ENV_FILE_PATH="$ROOT_DIR/env/profiles/${PROFILE}.env"
fi

if [[ -n "$MODE" && -n "$PROFILE" ]]; then
  echo "ERROR: --mode 与 --profile 不能同时使用"
  exit 1
fi

if [[ ! -f "$ENV_FILE_PATH" ]]; then
  echo "ERROR: env file not found: $ENV_FILE_PATH"
  exit 1
fi

if [[ -n "$MODE" ]]; then
  ENV_FILE="$ENV_FILE_PATH" "$ROOT_DIR/scripts/switch-model-mode.sh" "$MODE"
fi

export ENV_FILE="$ENV_FILE_PATH"
set -a
source "$ENV_FILE_PATH"
set +a

echo "Starting agent with ENV_FILE=$ENV_FILE_PATH MODEL_NAME=${MODEL_NAME:-}"
cd "$ROOT_DIR"
PYTHONPATH=src python3 -m beauty_saas_agent.server
