#!/usr/bin/env bash
set -euo pipefail

# Stream only the Easy-Turn runtime directory from the old AutoDL host to the
# new host. The destination is staged and the previous destination is kept as
# a timestamped backup instead of being deleted.

usage() {
  cat <<'EOF'
Usage:
  bash scripts/migrate_easyturn.sh <old-ssh-target> <new-ssh-target>

Examples:
  bash scripts/migrate_easyturn.sh \
    root@OLD_HOST \
    root@NEW_HOST

For non-default ports, create ~/.ssh/config entries first, for example:
  Host autodl-old
    HostName OLD_HOST
    Port OLD_PORT
    User root

  Host autodl-new
    HostName NEW_HOST
    Port NEW_PORT
    User root

Then run:
  bash scripts/migrate_easyturn.sh autodl-old autodl-new
EOF
}

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 2
fi

OLD_SSH="$1"
NEW_SSH="$2"
OLD_ROOT="/root/autodl-tmp/easyturn"
NEW_ROOT="/root/autodl-tmp/easyturn"
STAMP="$(date +%Y%m%d-%H%M%S)"
STAGE_ROOT="/root/autodl-tmp/.easyturn-migration-${STAMP}"
BACKUP_ROOT="/root/autodl-tmp/easyturn.before-migration-${STAMP}"

echo "[1/5] Checking the old host..."
ssh -T "$OLD_SSH" "test -d '$OLD_ROOT' && test -d '$OLD_ROOT/source' && test -d '$OLD_ROOT/models'"

echo "[2/5] Checking the new host's GPU visibility..."
if ssh -T "$NEW_SSH" "command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1"; then
  echo "GPU check passed."
else
  cat >&2 <<'EOF'
WARNING: the new host did not report a usable NVIDIA GPU.
Copying can continue, but Easy-Turn will not run until the new host exposes a GPU.
EOF
  read -r -p "Continue migration anyway? [y/N] " answer
  if [[ ! "$answer" =~ ^[Yy]$ ]]; then
    echo "Migration cancelled. Fix the new host GPU allocation/driver first."
    exit 1
  fi
fi

echo "[3/5] Streaming Easy-Turn files to a staging directory..."
ssh -T "$NEW_SSH" "mkdir -p '$STAGE_ROOT'"
set -o pipefail
ssh -T "$OLD_SSH" "tar -C '/root/autodl-tmp' -cf - 'easyturn'" \
  | ssh -T "$NEW_SSH" "tar -C '$STAGE_ROOT' -xf -"

echo "[4/5] Validating the staged files and switching directories..."
ssh -T "$NEW_SSH" "
  set -e
  test -f '$STAGE_ROOT/easyturn/source/Easy-Turn/Easy_Turn/web/app.py'
  test -d '$STAGE_ROOT/easyturn/models'
  test -f '$STAGE_ROOT/easyturn/local_demo/env.sh'
  if [ -e '$NEW_ROOT' ]; then
    mv '$NEW_ROOT' '$BACKUP_ROOT'
    echo 'Previous destination kept at: $BACKUP_ROOT'
  fi
  mv '$STAGE_ROOT/easyturn' '$NEW_ROOT'
  rmdir '$STAGE_ROOT' 2>/dev/null || true
"

echo "[5/5] Migration complete."
echo "New runtime: $NEW_SSH:$NEW_ROOT"
echo "Next checks on the new host:"
echo "  nvidia-smi"
echo "  du -sh $NEW_ROOT/models"
echo "  grep -n final_transcription_broadcast $NEW_ROOT/source/Easy-Turn/Easy_Turn/web/app.py"
