#!/usr/bin/env bash
# Reproducible TLS setup for pi.karotka.cz using acme.sh + Cloudflare DNS-01.
#
# This renews the Let's Encrypt cert that nginx serves on the LAN HTTPS path
# (see pi.karotka.cz site). It currently runs on the Pi4 (.222); run this on
# .224 as part of the Pi4 cutover so renewal survives the Pi4 being retired.
#
# The cert is EC-256, issued via a Cloudflare DNS-01 challenge (no port 80
# needed), and acme.sh installs its own daily cron — nothing else to schedule.
#
# Secrets are NOT in git. Before running, export:
#   export CF_Token="<Cloudflare API token, scoped: Zone.DNS:Edit for karotka.cz>"
#   export CF_Account_ID="<Cloudflare account id>"           # optional but recommended
#   export ACME_EMAIL="<your email for LE expiry notices>"   # optional
# Both live on .222 in ~/.acme.sh/account.conf (SAVED_CF_Token / SAVED_CF_Account_ID).
set -euo pipefail

DOMAIN=pi.karotka.cz
SSL_DIR=/etc/ssl/${DOMAIN}
RELOAD="sudo chgrp www-data ${SSL_DIR}/*.pem && sudo chmod 640 ${SSL_DIR}/*.pem && sudo systemctl reload nginx"

: "${CF_Token:?export CF_Token with a Cloudflare Zone.DNS:Edit token first}"

# 1. Install acme.sh once for the current user
if [ ! -d "$HOME/.acme.sh" ]; then
  curl -fsSL https://get.acme.sh | sh -s -- ${ACME_EMAIL:+email="$ACME_EMAIL"}
fi
export PATH="$HOME/.acme.sh:$PATH"

# 2. Use Let's Encrypt as the CA
acme.sh --set-default-ca --server letsencrypt

# 3. Issue via Cloudflare DNS-01 (EC-256), deploying to the paths nginx reads
sudo mkdir -p "$SSL_DIR"
acme.sh --issue --dns dns_cf -d "$DOMAIN" --keylength ec-256 \
  --key-file       "${SSL_DIR}/key.pem" \
  --fullchain-file "${SSL_DIR}/fullchain.pem" \
  --reloadcmd      "$RELOAD"

echo "Done. Cert at ${SSL_DIR}; acme.sh auto-renews ~30 days before expiry."
