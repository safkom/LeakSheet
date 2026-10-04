"""The API's own INFO lines reach stdout; library chatter, client IPs and HTTP statuses
do not reach GlitchTip.

gunicorn's UvicornWorker installs no logging config, so src.api sets one on import.
"""

import logging

import src.api  # noqa: F401 — importing the app is what configures logging

_DSN = "https://key@glitchtip.invalid/1"


def test_api_info_lines_are_emitted():
    assert logging.getLogger("src.api").isEnabledFor(logging.INFO)
    assert logging.getLogger("src.fetcher").isEnabledFor(logging.INFO)


def test_per_request_library_logs_stay_quiet():
    for name in ("httpx", "httpcore", "uvicorn.access"):
        assert not logging.getLogger(name).isEnabledFor(logging.INFO), name


def test_no_http_status_becomes_an_issue():
    for integration in src.api._sentry_options(_DSN)["integrations"]:
        assert not integration.failed_request_status_codes, type(integration).__name__


def test_client_ip_and_admin_token_headers_are_scrubbed():
    ip = "203.0.113.9"
    headers = {"cf-connecting-ip": ip, "true-client-ip": ip, "x-admin-token": "t", "user-agent": "ua"}
    event = {"request": {"headers": dict(headers)}}
    src.api._sentry_options(_DSN)["event_scrubber"].scrub_event(event)
    scrubbed = event["request"]["headers"]
    assert scrubbed["user-agent"] == "ua"
    for name in ("cf-connecting-ip", "true-client-ip", "x-admin-token"):
        assert scrubbed[name] != headers[name], name


def test_release_names_the_version():
    assert src.api._sentry_options(_DSN)["release"] == f"leaksheet-api@{src.api.VERSION}"
