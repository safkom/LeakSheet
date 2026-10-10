"""A malformed URL from a client is a 4xx on every endpoint, never a 500.

urlparse raises ValueError on an unclosed IPv6 bracket ("http://[::1") and on
an out-of-range port, so each place that parses a client's URL must turn that
into a client error. Production answered 500 on /sheet, /stream and
/image-proxy, and every one was filed as an unhandled error.
"""
import pytest

MALFORMED = ["http://[::1", "https://[", "http://]/"]


@pytest.mark.parametrize("url", [*MALFORMED, "https://docs.google.com:99999/x"])
def test_sheet(api_client, url):
    assert api_client.post("/sheet", json={"url": url}).status_code == 400


@pytest.mark.parametrize("url", MALFORMED)
@pytest.mark.parametrize("path", ["/stream", "/image-proxy", "/metadata"])
def test_get_endpoints(api_client, path, url):
    status = api_client.get(path, params={"url": url}).status_code
    assert 400 <= status < 500
