"""GET /health: the container HEALTHCHECK's probe, and where a deploy's version shows."""

import re

from src.config import VERSION


def test_health_is_uncached_and_names_the_version(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.json() == {"status": "ok", "version": VERSION}
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
