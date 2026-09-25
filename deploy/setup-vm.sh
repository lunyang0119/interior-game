#!/usr/bin/env bash
# One-time VM setup (Ubuntu 22.04/24.04 on Oracle Free Tier). Run ON THE VM as the default user (ubuntu):
#   curl -fsSL https://raw.githubusercontent.com/lunyang0119/interior-game/main/deploy/setup-vm.sh | bash
# Afterwards: fill /opt/interior/server/.env, then push gen/media/static from your PC with deploy/push.sh.
set -euo pipefail

REPO="https://github.com/lunyang0119/interior-game.git"
DIR=/opt/interior

sudo apt-get update -qq
sudo apt-get install -y -qq git python3 python3-venv python3-pip curl debian-keyring debian-archive-keyring apt-transport-https

# Caddy (official repo)
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq caddy
fi

# repo
if [[ ! -d $DIR/.git ]]; then
  sudo mkdir -p $DIR && sudo chown "$USER":"$USER" $DIR
  git clone -b main "$REPO" $DIR
fi
cd $DIR
python3 -m venv server/.venv
server/.venv/bin/pip install -q -e "server"

# env
if [[ ! -f server/.env ]]; then
  cp server/.env.example server/.env
  sed -i "s|^IP_SALT=.*|IP_SALT=$(head -c 32 /dev/urandom | base64 | tr -d '/+=')|" server/.env
  echo ">>> EDIT $DIR/server/.env : SHEET_URL, DUCKDNS_TOKEN"
fi

# systemd + caddy
sudo sed "s|^User=.*|User=$USER|" deploy/interior.service | sudo tee /etc/systemd/system/interior.service >/dev/null
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl enable --now interior caddy

# Oracle images ship with iptables rules that drop 80/443: open them and persist
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo apt-get install -y -qq iptables-persistent >/dev/null 2>&1 || true
sudo netfilter-persistent save >/dev/null 2>&1 || true

# DuckDNS refresh every 5 minutes
chmod +x deploy/duckdns.sh
( crontab -l 2>/dev/null | grep -v duckdns.sh; echo "*/5 * * * * $DIR/deploy/duckdns.sh >/dev/null 2>&1" ) | crontab -

echo "done. Next: edit server/.env, then from your PC run deploy/push.sh <user>@<vm-ip>"
echo "Also open 80/443 in the Oracle console: VCN → Security List → Ingress rules."
