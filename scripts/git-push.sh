#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="${1:-$ROOT_DIR/env/git-push.local.env}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "ERROR: config file not found: $CONFIG_FILE"
  echo "You can copy: $ROOT_DIR/env/git-push.example.env -> $ROOT_DIR/env/git-push.local.env"
  exit 1
fi

set -a
source "$CONFIG_FILE"
set +a

if [[ -z "${GIT_REMOTE_SSH:-}" ]]; then
  echo "ERROR: GIT_REMOTE_SSH is empty in $CONFIG_FILE"
  exit 1
fi

BRANCH="${GIT_BRANCH:-main}"
KEY_PATH_RAW="${SSH_PRIVATE_KEY:-~/.ssh/id_ed25519}"
KEY_PATH="${KEY_PATH_RAW/#\~/$HOME}"

if [[ ! -f "$KEY_PATH" ]]; then
  echo "ERROR: SSH key not found: $KEY_PATH"
  exit 1
fi

SSH_CMD="ssh -i \"$KEY_PATH\" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

if git -C "$ROOT_DIR" remote get-url origin >/dev/null 2>&1; then
  git -C "$ROOT_DIR" remote set-url origin "$GIT_REMOTE_SSH"
else
  git -C "$ROOT_DIR" remote add origin "$GIT_REMOTE_SSH"
fi

echo "Using remote: $GIT_REMOTE_SSH"
echo "Pushing branch: $BRANCH"
GIT_SSH_COMMAND="$SSH_CMD" git -C "$ROOT_DIR" push -u origin "$BRANCH"
