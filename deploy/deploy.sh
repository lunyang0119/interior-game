#!/usr/bin/env bash
# Run ON THE VM as the service user, from /opt/interior:
#   ./deploy/deploy.sh            # git pull, build client, install server, restart
#   ./deploy/deploy.sh --no-build # skip npm (when you rsync server/static from your PC instead)
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only

if [[ "${1:-}" != "--no-build" ]]; then
  # Generated sprites are gitignored: copy them from your PC once with
  #   rsync -av client/public/gen/ ubuntu@VM:/opt/interior/client/public/gen/
  (cd client && npm ci --silent && npm run build)
fi

(cd server && [[ -d .venv ]] || python3 -m venv .venv)
(cd server && .venv/bin/pip install -q -e .)

sudo systemctl restart interior
sudo systemctl --no-pager --lines=5 status interior
