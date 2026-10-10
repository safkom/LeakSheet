#!/bin/sh
# Time the API container's path to Google one layer at a time (DNS, TCP, TLS, a full
# page), to explain slow cold loads. Read-only: run on the server, paste the table.
#   ops/diag-upstream.sh [container]    (default: the running leaksheet-api container)
set -eu
c="${1:-$(docker ps -q --filter ancestor=leaksheet-api:latest | head -n 1)}"
[ -n "$c" ] || { echo "no running leaksheet-api container; pass its name" >&2; exit 1; }
docker exec -i -w /app "$c" python - <<'EOF'
import asyncio, socket, ssl, statistics, time

import httpx

from src.streaming import PublicOnlyAsyncTransport

HOST = "docs.google.com"
# A public tracker page from tests/live_trackers.txt (~55 KB).
URL = "https://docs.google.com/spreadsheets/d/1v55XAPLzw1iuWxH1OQKajCIYPhW2BXcLoV4mXDZ55DI/htmlview"
RUNS = 5
rows = []


def timed(fn):
    out = []
    for _ in range(RUNS):
        t = time.perf_counter()
        try:
            fn()
            out.append(time.perf_counter() - t)
        except Exception as e:
            out.append(f"{type(e).__name__}: {e}"[:60])
    return out


for fam, name in [(socket.AF_INET, "dns A"), (socket.AF_INET6, "dns AAAA")]:
    rows.append((name, timed(lambda: socket.getaddrinfo(HOST, 443, fam, socket.SOCK_STREAM))))

for fam, name in [(socket.AF_INET, "v4"), (socket.AF_INET6, "v6")]:
    try:
        addr = socket.getaddrinfo(HOST, 443, fam, socket.SOCK_STREAM)[0][4][:2]
    except OSError as e:
        rows.append((f"tcp+tls {name}", [f"no address: {e}"[:60]]))
        continue
    rows.append((f"tcp {name}", timed(lambda: socket.create_connection(addr, timeout=15).close())))
    ctx = ssl.create_default_context()
    rows.append((f"tcp+tls {name}", timed(
        lambda: ctx.wrap_socket(socket.create_connection(addr, timeout=15), server_hostname=HOST).close()
    )))


async def page(transport_factory, reuse):
    out = []
    shared = httpx.AsyncClient(transport=transport_factory(), timeout=60) if reuse else None
    for _ in range(RUNS):
        client = shared or httpx.AsyncClient(transport=transport_factory(), timeout=60)
        t = time.perf_counter()
        try:
            r = await client.get(URL)
            out.append(time.perf_counter() - t if r.status_code == 200 else f"HTTP {r.status_code}")
        except Exception as e:
            out.append(f"{type(e).__name__}: {e}"[:60])
        if not reuse:
            await client.aclose()
    if shared:
        await shared.aclose()
    return out

rows.append(("GET page, new conn", asyncio.run(page(httpx.AsyncHTTPTransport, False))))
rows.append(("GET page, app transport", asyncio.run(page(PublicOnlyAsyncTransport, False))))
rows.append(("GET page, reused conn", asyncio.run(page(PublicOnlyAsyncTransport, True))))

print(f"{'step':26} {'min ms':>8} {'median':>8} {'max ms':>8}  errors")
for name, vals in rows:
    nums = [v * 1000 for v in vals if isinstance(v, float)]
    errs = sorted({v for v in vals if not isinstance(v, float)})
    if nums:
        print(f"{name:26} {min(nums):8.0f} {statistics.median(nums):8.0f} {max(nums):8.0f}  {'; '.join(errs)}")
    else:
        print(f"{name:26} {'-':>8} {'-':>8} {'-':>8}  {'; '.join(errs)}")
EOF
