#!/bin/sh
# Deploy origin/main on the homelab: build the images from this checkout, then restart the
# CasaOS app `leaksheet` from ops/casaos/leaksheet.yml with ~/LeakSheet/.env filled in.
# Never `docker compose up` in the checkout itself: that starts a second, legacy copy.
set -eu
cd "$(dirname "$0")/.."
git fetch -q origin && git reset -q --hard origin/main
docker compose build -q api web
set -a; [ -f .env ] && . ./.env; set +a
export LEAKSHEET_TRUSTED_PROXY_HOPS="${LEAKSHEET_TRUSTED_PROXY_HOPS:-}" \
       LEAKSHEET_RATE_LIMIT_PER_MIN="${LEAKSHEET_RATE_LIMIT_PER_MIN:-}" SENTRY_DSN="${SENTRY_DSN:-}"
python3 -c 'import os, sys; sys.stdout.write(os.path.expandvars(open(sys.argv[1]).read()))' \
  ops/casaos/leaksheet.yml |
  docker run --rm -i -v /var/lib/casaos/apps:/apps alpine \
    sh -c 'mkdir -p /apps/leaksheet && cat > /apps/leaksheet/docker-compose.yml && chmod 600 /apps/leaksheet/docker-compose.yml'
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v /var/lib/casaos/apps:/var/lib/casaos/apps \
  -w /var/lib/casaos/apps/leaksheet docker:cli compose up -d
git log --oneline -1
