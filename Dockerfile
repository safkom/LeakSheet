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

EXPOSE 8080
# /health, not /docs: probing the docs route rendered the whole Swagger page
# and silently made the container's liveness depend on docs staying enabled.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=3)" || exit 1
# --timeout 120: the default is 30s, and for UvicornWorker that is a liveness
#   watchdog on the event loop — a cold Ye-sized parse can block it long
#   enough to have the worker killed mid-request.
# --workers 1: load-bearing, not a default worth inheriting. README.md
#   documents that the box cannot fit two concurrent Ye-sized cold parses.
CMD ["gunicorn", "src.api:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "1", "--timeout", "120", "--graceful-timeout", "30", \
     "--bind", "0.0.0.0:8080"]
