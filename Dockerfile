FROM python:3.11-slim

# Pinned, not :latest — a floating installer would undo the point of uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies layer before the source. --locked fails on uv.lock/pyproject drift
# (--frozen would not check); --no-cache keeps uv's download cache out of the layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache

COPY src ./src

# The venv uv builds, so `gunicorn` and `python` below resolve to it.
ENV PATH="/app/.venv/bin:$PATH"

# Non-root: /sheet fetches attacker-influenced URLs and Pillow decodes untrusted
# images. The app writes only to the mounted cache volume, chowned to this uid.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8080
# Every probe counts toward --max-requests and starts a Python, so probe rarely once up;
# --start-interval keeps `depends_on: service_healthy` fast at boot.
HEALTHCHECK --interval=5m --timeout=5s --retries=3 --start-period=60s --start-interval=2s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=3)" || exit 1
# --timeout 90: UvicornWorker's event-loop watchdog. Must clear a cold Ye-sized parse
#   yet stay under Cloudflare's 125 s edge read timeout (fixed below Enterprise).
# --workers 3: a parse blocks its worker's event loop (~1.3GB resident each). The
#   rate limiter and in-process caches are per worker.
# --max-requests 1000 (+jitter): recycling bounds lxml arena fragmentation; the
#   jitter keeps all three workers from recycling at once.
CMD ["gunicorn", "src.api:app", \
     "--worker-class", "uvicorn_worker.UvicornWorker", \
     "--workers", "3", "--timeout", "90", "--graceful-timeout", "30", \
     "--max-requests", "1000", "--max-requests-jitter", "100", \
     "--bind", "0.0.0.0:8080"]
