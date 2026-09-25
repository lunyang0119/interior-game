#!/usr/bin/env bash
# Run ON YOUR PC (Git Bash) from the repo root:
#   ./deploy/push.sh ubuntu@1.2.3.4          # build client, push gen/ media/ static/, restart service
#   ./deploy/push.sh ubuntu@1.2.3.4 --no-build
# Requires ssh access to the VM (key in ~/.ssh or ssh-agent) and deploy/setup-vm.sh done once on the VM.
set -euo pipefail
cd "$(dirname "$0")/.."

VM="${1:?usage: deploy/push.sh user@host [--no-build]}"
DIR=/opt/interior

if [[ "${2:-}" != "--no-build" ]]; then
  (cd client && npm run build)
fi

git push origin HEAD:main

# gitignored build outputs: sprites, media (bgm/fonts/ui), static bundle
tar czf - client/public/gen client/public/media server/static | ssh "$VM" "tar xzf - -C $DIR"

ssh "$VM" "cd $DIR && git pull --ff-only && server/.venv/bin/pip install -q -e server && sudo systemctl restart interior && sleep 1 && systemctl --no-pager --lines=3 status interior"
echo "pushed → https://crystalroom.duckdns.org"
