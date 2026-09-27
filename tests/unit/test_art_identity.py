"""An Art-tab cover replaces the main-tab one only when it is the same picture.

Adopted by name alone, Ye's Art tab replaced 42 of 43 covers and Yandhi [V2] showed a
single's art. See docs/decisions.md::fetcher.py::art-tab-identity.
"""

from __future__ import annotations

import asyncio
import io

from PIL import Image, ImageDraw

import src.fetcher as fetcher
from src.models import Artist, Era


def _art(seed: int, size: int, fmt: str = "PNG") -> bytes:
    """A distinct picture per seed, rendered at *size* px."""
    img = Image.new("RGB", (400, 400), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    for i in range(5):
        x = (seed * 97 + i * 71) % 300
        y = (seed * 53 + i * 131) % 300
        draw.ellipse((x, y, x + 100, y + 100), fill=((seed * 60 + i * 40) % 255, 200, 90))
    buf = io.BytesIO()
    img.resize((size, size)).save(buf, format=fmt)
    return buf.getvalue()


def test_the_same_picture_at_another_size_and_format_matches():
    assert fetcher.same_artwork(_art(1, 102, "JPEG"), _art(1, 340))


def test_different_pictures_do_not_match():
    assert not fetcher.same_artwork(_art(1, 102, "JPEG"), _art(2, 340))


def test_undecodable_bytes_never_match():
    assert not fetcher.same_artwork(b"<html>403</html>", _art(1, 340))


def test_only_matching_covers_are_adopted(monkeypatch):
    images = {
        "main-a": _art(1, 102, "JPEG"), "tab-a": _art(1, 340),   # same art: upgrade
        "main-b": _art(2, 102, "JPEG"), "tab-b": _art(3, 340),   # another picture: keep
        "main-c": _art(4, 102, "JPEG"),                          # tab image dead: keep
    }

    async def fake_fetch(url, slots):
        return images.get(url)

    monkeypatch.setattr(fetcher, "_fetch_art", fake_fetch)
    artist = Artist(name="X", slug="x", eras=[
        Era(name="A", art_url="main-a"), Era(name="B", art_url="main-b"), Era(name="C", art_url="main-c"),
    ])
    asyncio.run(fetcher._adopt_matching_art(artist, {"A": "tab-a", "B": "tab-b", "C": "tab-c"}))
    assert [e.art_url for e in artist.eras] == ["tab-a", "main-b", "main-c"]
