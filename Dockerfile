FROM python:3.11-slim

# Pinned, not :latest — a floating installer would undo the point of uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies in their own layer, before the source: editing src/ then rebuilds
# without re-resolving. --locked fails the build if uv.lock and pyproject.toml
# have drifted apart (--frozen would install the stale lock without checking).
# --no-cache keeps uv's download cache out of the image layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache

COPY src ./src

# The venv uv builds, so `gunicorn` and `python` below resolve to it.
ENV PATH="/app/.venv/bin:$PATH"

# Non-root at runtime: /sheet fetches attacker-influenced URLs and /image-proxy
# decodes attacker-supplied images with Pillow, so root is the wrong ambient
# authority. Nothing the app writes lives in the image — only the mounted cache
# volume, which the deploy chowns to this uid.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8080
# /health, not /docs: probing the docs route rendered the whole Swagger page
# and silently made the container's liveness depend on docs staying enabled.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=3)" || exit 1
# --timeout 90: the default is 30s, and for UvicornWorker this is a liveness
#   watchdog on the event loop — a cold Ye-sized parse blocks it, so the value
#   has to clear a real parse. It also has to stay UNDER Cloudflare's edge read
#   timeout, which the zone reports as 125s and which is not raisable below
#   Enterprise, so a wedged worker is recycled before the edge gives up and
#   answers 524 on its own.
# --workers 3: a parse blocks its worker's event loop, so one worker means one
#   cold parse stalls every other request. Three fit with room to spare (~1.3GB
#   resident each against the host's 15GB and this container's 6g cap).
#   Consequence: the rate limiter, _cdn_url_cache and _inflight_resolves are all
#   in-process and therefore per-worker now — see src/api.py's rate-limit
#   docstring. LEAKSHEET_PREWARM must stay 0 (docker-compose.yml explains why).
# --max-requests 200 (+jitter): each worker holds ~1.3GB resident parsing with
#   lxml, and nothing here frees an arena that fragments. Recycling bounds that
#   without a restart being visible — with three workers the other two serve
#   while one respawns. The jitter stops all three recycling on the same
#   request count and briefly leaving none.
CMD ["gunicorn", "src.api:app", \
     "--worker-class", "uvicorn_worker.UvicornWorker", \
     "--workers", "3", "--timeout", "90", "--graceful-timeout", "30", \
     "--max-requests", "200", "--max-requests-jitter", "50", \
     "--bind", "0.0.0.0:8080"]
