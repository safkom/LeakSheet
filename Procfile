# Single worker on purpose: the 512MB box can't fit two concurrent Ye-sized
# cold parses (11.7MB HTML → model tree + serialized dict each). CPU-bound
# parse/serialize work is pushed off the event loop via asyncio.to_thread,
# so the single worker stays responsive during a cold miss.
web: gunicorn src.api:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8080}
