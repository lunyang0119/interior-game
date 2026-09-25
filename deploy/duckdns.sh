#!/bin/sh
# Updates the DuckDNS record with this VM's public IP.
# crontab -e →  */5 * * * * /opt/interior/deploy/duckdns.sh >/dev/null 2>&1
DOMAIN="YOURNAME"       # subdomain without .duckdns.org
TOKEN="your-duckdns-token"
curl -s "https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip="
