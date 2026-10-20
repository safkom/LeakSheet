"""Deploy and proxy config invariants that only bite in production."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NGINX = (ROOT / "web" / "nginx.conf").read_text()
COMPOSE = (ROOT / "ops" / "casaos" / "leaksheet.yml").read_text()
DEPLOY = (ROOT / "ops" / "deploy.sh").read_text()


def test_nginx_re_resolves_the_api_upstream():
    """A literal proxy_pass host resolves once at start: recreating only api leaves a dead IP."""
    assert "resolver 127.0.0.11" in NGINX
    assert "proxy_pass $" in NGINX
    assert "proxy_pass http://api" not in NGINX


def test_nginx_never_sends_a_decoded_uri_upstream():
    """$uri is decoded: %0d%0a in it would reach the API as raw CRLF (header injection)."""
    block = NGINX.split("location /api/", 1)[1].split("}", 1)[0]
    code = "\n".join(line for line in block.splitlines() if not line.strip().startswith("#"))
    assert "$uri" not in code and "rewrite" not in code
    assert "proxy_pass $api_upstream$api_uri;" in code
    assert "$request_uri" in NGINX


def test_nginx_trusts_forwarded_for_only_from_the_tunnel_side():
    """A LAN client on :8081 must not pick its own rate-limit bucket with X-Forwarded-For."""
    assert "geo $remote_addr $from_tunnel" in NGINX
    assert "proxy_set_header X-Forwarded-For $leak_xff;" in NGINX
    assert "$proxy_add_x_forwarded_for" in NGINX  # kept for the tunnel path
    assert "X-Forwarded-For $proxy_add_x_forwarded_for;" not in NGINX


def test_api_gets_a_grace_period_longer_than_gunicorns():
    assert "stop_grace_period: 35s" in COMPOSE


def test_web_restarts_with_api():
    assert "restart: true" in COMPOSE


def test_deploy_recreates_web():
    assert "--force-recreate" in DEPLOY and "web" in DEPLOY.split("--force-recreate", 1)[1].splitlines()[0]


@pytest.mark.parametrize(("rate", "hops", "ok"), [
    ("60", "", False),
    ("60", "2", True),
    ("", "", True),
    ("", "2", True),
])
def test_deploy_refuses_a_rate_limit_without_trusted_hops(rate, hops, ok):
    done = subprocess.run(
        ["sh", str(ROOT / "ops" / "check-env.sh")],
        env={"LEAKSHEET_RATE_LIMIT_PER_MIN": rate, "LEAKSHEET_TRUSTED_PROXY_HOPS": hops, "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    assert (done.returncode == 0) is ok
    if not ok:
        assert "LEAKSHEET_TRUSTED_PROXY_HOPS" in done.stderr
