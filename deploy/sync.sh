#!/usr/bin/env bash
# Run ON YOUR PC (Git Bash) from the repo root — copies everything the VM needs in one go, no git, no SFTP:
#   ./deploy/sync.sh ubuntu@1.2.3.4            # build client → tar | ssh → /opt/interior → restart service
#   ./deploy/sync.sh ubuntu@1.2.3.4 --no-build  # skip the client build
#   ./deploy/sync.sh ubuntu@1.2.3.4 --no-restart
#   ./deploy/sync.sh ubuntu@1.2.3.4 --media      # also client/public/media (BGM/fonts/sfx, ~270 MB; only after `media`/`ui` builds)
#   ./deploy/sync.sh ubuntu@1.2.3.4 --force      # overwrite data/ the VM editor changed without asking
#   VM=ubuntu@1.2.3.4 ./deploy/sync.sh          # or put the host in $VM once (e.g. in ~/.bashrc)
# Needs ssh key access to the VM (the same you use for SFTP). Never touches server/.env, the DB or the venv there.
# data/ can also be edited ON the VM (edit.<host>, the VM editor): before uploading, this checks the VM's data/
# against the stamp of the last sync/pull and asks before overwriting newer edits — ./deploy/pull.sh gets them first.
set -euo pipefail
cd "$(dirname "$0")/.."
. deploy/lib.sh

VM="${1:-${VM:-}}"
[[ -n "$VM" ]] || { echo "usage: deploy/sync.sh user@host [--no-build] [--no-restart] [--media] [--force]  (or export VM=user@host)"; exit 1; }
BUILD=1 RESTART=1 MEDIA=0 FORCE=0
for a in "${@:2}"; do
  case "$a" in
    --no-build) BUILD=0 ;;
    --no-restart) RESTART=0 ;;
    --media) MEDIA=1 ;;
    --force) FORCE=1 ;;
    *) echo "unknown option $a"; exit 1 ;;
  esac
done

if [[ $FORCE == 0 ]] && ! vm_data_unchanged "$VM"; then
  echo "!! VM의 data/ 가 마지막 sync/pull 이후 바뀌었어요 (VM 에디터로 고친 것). 지금 올리면 그 편집이 사라져요."
  echo "   먼저  ./deploy/pull.sh $VM  로 가져오는 게 안전해요."
  read -r -p "   그래도 PC 내용으로 덮어쓸까요? [y/N] " ans </dev/tty
  [[ ${ans,,} == y* ]] || { echo "중단"; exit 1; }
fi

if [[ $BUILD == 1 ]]; then
  (cd client && npm run build)
fi

# What the running server reads: code, migrations, package metadata, game data, built client + sprites (~10 MB),
# plus the editor (tools/preprocess: runs on the VM in --vm mode; contact sheets/tests/PC upload state left out).
# Media (BGM/fonts/sfx) only with --media. Excluded: server/.env (VM has its own), interior.db, the venv, caches.
PATHS=(server/app server/migrations server/pyproject.toml data client/public/gen server/static tools/preprocess deploy)
[[ $MEDIA == 1 ]] && PATHS+=(client/public/media)
echo "→ $VM:$DIR  (${PATHS[*]})"
tar czf - \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' --exclude='*.db' --exclude='*.db-*' \
  --exclude='tools/preprocess/contact_*.png' --exclude='tools/preprocess/tests' --exclude='.deploy_state.json' \
  "${PATHS[@]}" | ssh "$VM" "tar xzf - -C $DIR --no-same-owner && echo '  unpacked'"
vm_stamp "$VM"

if [[ $RESTART == 1 ]]; then
  ssh "$VM" "sudo systemctl restart interior && sleep 1 && systemctl --no-pager --lines=5 status interior"
else
  echo "  (no restart; run: ssh $VM sudo systemctl restart interior)"
fi
