#!/usr/bin/env bash
set -euo pipefail

# Upload the patched Easy-Turn ASR adapter to an AutoDL host.
# The old remote file is backed up before the new file is atomically installed.

usage() {
  cat <<'EOF'
Usage:
  bash scripts/sync_easyturn_short_words.sh <autodl-ssh-target> [remote-root]

Examples:
  bash scripts/sync_easyturn_short_words.sh root@1.2.3.4
  bash scripts/sync_easyturn_short_words.sh autodl-easyturn /root/autodl-tmp/easyturn

Optional restart after a successful upload:
  EASYTURN_RESTART_COMMAND='bash /root/autodl-tmp/easyturn/restart.sh' \
    bash scripts/sync_easyturn_short_words.sh root@1.2.3.4

For a non-default SSH port, put the host and port in ~/.ssh/config, then use
the configured host alias as the first argument.
EOF
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage >&2
  exit 2
fi

SSH_TARGET="$1"
REMOTE_ROOT="${2:-${EASYTURN_REMOTE_ROOT:-/root/autodl-tmp/easyturn}}"
RESTART_COMMAND="${EASYTURN_RESTART_COMMAND:-}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SOURCE_FILE="$PROJECT_ROOT/.local-reference/easyturn-cloud-snapshot/easyturn-code/easyturn/source/Easy-Turn/Easy_Turn/web/english_asr.py"
REMOTE_WEB_DIR="$REMOTE_ROOT/source/Easy-Turn/Easy_Turn/web"
REMOTE_FILE="$REMOTE_WEB_DIR/english_asr.py"
REMOTE_TMP="$REMOTE_WEB_DIR/.english_asr.py.sync.$$.$RANDOM"

if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "Local source file not found:" >&2
  echo "  $SOURCE_FILE" >&2
  exit 1
fi

for command_name in ssh scp; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 1
  fi
done

# Quote a value for inclusion in a POSIX shell command sent over SSH.
shell_quote() {
  local value="$1"
  value="${value//\'/\'\\\'\'}"
  printf "'%s'" "$value"
}

REMOTE_ROOT_Q="$(shell_quote "$REMOTE_ROOT")"
REMOTE_WEB_DIR_Q="$(shell_quote "$REMOTE_WEB_DIR")"
REMOTE_TMP_Q="$(shell_quote "$REMOTE_TMP")"
REMOTE_FILE_Q="$(shell_quote "$REMOTE_FILE")"

cleanup() {
  if [[ -n "${REMOTE_TMP:-}" ]]; then
    ssh -T "$SSH_TARGET" "rm -f -- $REMOTE_TMP_Q" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[1/4] Checking the AutoDL destination..."
ssh -T "$SSH_TARGET" "mkdir -p -- $REMOTE_WEB_DIR_Q"

echo "[2/4] Uploading the patched english_asr.py..."
scp "$SOURCE_FILE" "$SSH_TARGET:$REMOTE_TMP"

REMOTE_COMMAND="bash -s -- $REMOTE_ROOT_Q $REMOTE_TMP_Q $REMOTE_FILE_Q"
if [[ -n "$RESTART_COMMAND" ]]; then
  RESTART_COMMAND_Q="$(shell_quote "$RESTART_COMMAND")"
  REMOTE_COMMAND="EASYTURN_RESTART_COMMAND=$RESTART_COMMAND_Q $REMOTE_COMMAND"
fi

echo "[3/4] Validating and atomically installing the file..."
ssh -T "$SSH_TARGET" "$REMOTE_COMMAND" <<'REMOTE_SCRIPT'
set -euo pipefail

remote_root="$1"
remote_tmp="$2"
remote_file="$3"
restart_command="${EASYTURN_RESTART_COMMAND:-}"
backup_dir="$remote_root/backups/asr"

test -s "$remote_tmp"
python3 -m py_compile "$remote_tmp"

mkdir -p -- "$backup_dir"
if [[ -f "$remote_file" ]]; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  backup_file="$backup_dir/english_asr.py.$stamp"
  cp -p -- "$remote_file" "$backup_file"
  chmod --reference="$remote_file" "$remote_tmp" 2>/dev/null || true
  echo "Backup created: $backup_file"
fi

mv -f -- "$remote_tmp" "$remote_file"
python3 -m py_compile "$remote_file"

if [[ -n "$restart_command" ]]; then
  echo "Restarting Easy-Turn with: $restart_command"
  bash -lc "$restart_command"
else
  echo "No restart command supplied. Restart Easy-Turn manually before testing."
fi
REMOTE_SCRIPT

echo "[4/4] Sync complete: $SSH_TARGET:$REMOTE_FILE"
