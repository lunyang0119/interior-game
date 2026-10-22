#!/usr/bin/env bash
# Run ON YOUR PC (Git Bash) from the repo root — the reverse of sync.sh, for what the VM editor can change:
#   ./deploy/pull.sh ubuntu@1.2.3.4      # VM data/ + gen/dock.json → here, then `git status` so you can commit
#   VM=ubuntu@1.2.3.4 ./deploy/pull.sh
# Asks before overwriting uncommitted PC changes to those files. Files deleted on the VM (a removed room) are
# not deleted here — check the status output. Refreshes the VM stamp, so the next sync.sh will not warn.
set -euo pipefail
cd "$(dirname "$0")/.."
. deploy/lib.sh

VM="${1:-${VM:-}}"
[[ -n "$VM" ]] || { echo "usage: deploy/pull.sh user@host  (or export VM=user@host)"; exit 1; }
# shellcheck disable=SC2206
PATHS=($EDITABLE)

if dirty=$(git status --porcelain -- "${PATHS[@]}") && [[ -n $dirty ]]; then
  echo "!! PC에 커밋 안 한 변경이 있어요 (VM 내용으로 덮어써져요):"
  echo "$dirty"
  read -r -p "   계속할까요? [y/N] " ans </dev/tty
  [[ ${ans,,} == y* ]] || { echo "중단"; exit 1; }
fi

echo "← $VM:$DIR  (${PATHS[*]})"
ssh "$VM" "tar czf - -C $DIR ${PATHS[*]}" | tar xzf -
vm_stamp "$VM"
echo "바뀐 파일:"
git status --short -- "${PATHS[@]}"
echo "→ 확인하고 커밋해요. 로컬 서버가 떠 있으면 다시 시작, 에디터는 새로고침."
