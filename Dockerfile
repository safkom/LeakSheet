FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
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
