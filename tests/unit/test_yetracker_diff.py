"""The yetracker.cc diff tool must not write into the cache it is pointed at."""

from types import SimpleNamespace

from src import fetcher
from tests.tools import yetracker_diff


def test_local_parse_leaves_the_corpus_cache_untouched(monkeypatch):
    corpus = fetcher.CACHE_DIR  # conftest's per-test dir stands in for the real corpus
    seen = []

    async def fake_fetch_and_parse(url, **kwargs):
        seen.append(fetcher.CACHE_DIR)
        # _finalize writes a cover pointer on every parse
        fetcher.update_art_pointer("leaksheet:art/v2/t/e", src="https://example.test/a.jpg")
        return SimpleNamespace(model_dump_json=lambda: "{}")

    monkeypatch.setattr(fetcher, "async_fetch_and_parse", fake_fetch_and_parse)

    assert yetracker_diff.ours(None) == {}
    assert seen
    assert seen[0] != corpus
    assert list(corpus.glob("imgsrc_*")) == []
    assert fetcher.CACHE_DIR == corpus
