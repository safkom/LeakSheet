#!/bin/sh
# A rate limit without trusted proxy hops buckets every client under the proxy's address.
set -eu
if [ -n "${LEAKSHEET_RATE_LIMIT_PER_MIN:-}" ] && [ -z "${LEAKSHEET_TRUSTED_PROXY_HOPS:-}" ]; then
  echo "LEAKSHEET_RATE_LIMIT_PER_MIN is set but LEAKSHEET_TRUSTED_PROXY_HOPS is empty" >&2
  exit 1
fi
