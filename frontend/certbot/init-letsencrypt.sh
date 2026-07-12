#!/usr/bin/env bash
# One-time TLS bootstrap: seed a dummy self-signed cert so nginx can boot on
# :443, bring the stack up, then replace it with a real Let's Encrypt cert.
# Run from the frontend/ directory after editing .env.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Create .env first (cp .env.example .env)"; exit 1; }
set -a; . ./.env; set +a

: "${DOMAIN:?set DOMAIN in .env}"
: "${LETSENCRYPT_EMAIL:?set LETSENCRYPT_EMAIL in .env}"
STAGING="${STAGING:-1}"

CONF="./certbot/conf"
LIVE="$CONF/live/$DOMAIN"

echo "### Seeding a temporary self-signed certificate for $DOMAIN"
mkdir -p "$LIVE" "./certbot/www"
docker run --rm -v "$PWD/certbot/conf:/etc/letsencrypt" --entrypoint openssl \
  certbot/certbot req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout "/etc/letsencrypt/live/$DOMAIN/privkey.pem" \
  -out "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" \
  -subj "/CN=$DOMAIN"

echo "### Starting nginx + frontend"
docker compose up -d --build frontend nginx

echo "### Deleting dummy certificate"
docker compose run --rm --entrypoint \
  "sh -c 'rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf'" \
  certbot

echo "### Requesting a real Let's Encrypt certificate for $DOMAIN"
STAGING_FLAG=""
[ "$STAGING" != "0" ] && STAGING_FLAG="--staging"
docker compose run --rm --entrypoint \
  "certbot certonly --webroot -w /var/www/certbot $STAGING_FLAG \
   --email $LETSENCRYPT_EMAIL -d $DOMAIN --rsa-key-size 2048 \
   --agree-tos --no-eff-email --force-renewal" certbot

echo "### Reloading nginx"
docker compose exec nginx nginx -s reload

echo "### Done. Bringing up the full stack (incl. certbot renew loop)."
docker compose up -d
