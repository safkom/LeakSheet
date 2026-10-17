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


_KEY = "AIzaTestOnlyNotARealKey000000000000000"


def _contains_key(payload) -> bool:
    import json

    return _KEY in json.dumps(payload, default=repr)


def test_the_google_key_is_scrubbed_by_value_everywhere(monkeypatch):
    # Frame locals are scrubbed only by variable name; a key can sit under any name.
    monkeypatch.setenv("LEAKSHEET_GOOGLE_API_KEY", _KEY)
    options = src.api._sentry_options(_DSN)
    event = {
        "exception": {"values": [{"value": f"boom {_KEY}", "stacktrace": {"frames": [
            {"vars": {"headers": f"[(b'x-goog-api-key', b'{_KEY}')]", "n": 3}}]}}]},
        "breadcrumbs": {"values": [{"message": f"GET with {_KEY}"}]},
        "extra": {"kept": "no secret here"},
    }
    scrubbed = options["before_send"](event, {})
    assert not _contains_key(scrubbed)
    assert scrubbed["extra"]["kept"] == "no secret here"
    assert scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]["n"] == 3
    log = {"body": f"line {_KEY}", "attributes": {"x": _KEY}}
    assert not _contains_key(options["before_send_log"](log, {}))


def test_a_real_error_event_never_carries_the_key(monkeypatch):
    import sentry_sdk
    from sentry_sdk.transport import Transport

    monkeypatch.setenv("LEAKSHEET_GOOGLE_API_KEY", _KEY)
    sent: list = []

    class Capture(Transport):
        def capture_envelope(self, envelope):
            sent.extend(item.get_bytes() for item in envelope.items)

    client = sentry_sdk.Client(**src.api._sentry_options(_DSN), transport=Capture())

    def failing(api_key_header=[(b"x-goog-api-key", _KEY.encode())], innocuous=_KEY):  # noqa: B006
        raise RuntimeError("transport bug")

    with sentry_sdk.new_scope() as scope:
        scope.set_client(client)
        try:
            failing()
        except RuntimeError:
            scope.capture_exception()
    client.flush()
    assert sent, "the event was not captured"
    assert not any(_KEY.encode() in body for body in sent)
