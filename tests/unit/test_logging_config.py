"""The API's own INFO lines reach stdout; per-request library chatter does not.

gunicorn's UvicornWorker installs no logging config, so without one the root logger
kept Python's WARNING default and every `sheet_timing` line was dropped in production.
"""

import logging

import src.api  # noqa: F401 — importing the app is what configures logging


def test_api_info_lines_are_emitted():
    assert logging.getLogger("src.api").isEnabledFor(logging.INFO)
    assert logging.getLogger("src.fetcher").isEnabledFor(logging.INFO)


def test_per_request_library_logs_stay_quiet():
    for name in ("httpx", "httpcore", "uvicorn.access"):
        assert not logging.getLogger(name).isEnabledFor(logging.INFO), name
