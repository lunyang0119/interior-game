#!/bin/sh
# Updates the DuckDNS record with this VM's public IP.
# Token lives in server/.env (gitignored) as DUCKDNS_TOKEN — never hardcode it here.
# crontab -e →  */5 * * * * /opt/interior/deploy/duckdns.sh >/dev/null 2>&1
DOMAIN="crystalroom"
ENV_FILE="$(dirname "$0")/../server/.env"
TOKEN="$(grep -E '^DUCKDNS_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
[ -n "$TOKEN" ] || { echo "DUCKDNS_TOKEN missing in $ENV_FILE" >&2; exit 1; }
curl -s "https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip="
