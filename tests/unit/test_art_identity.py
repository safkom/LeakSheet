"""An Art-tab cover replaces the main-tab one only when it is the same picture.

Adopted by name alone, Ye's Art tab replaced 42 of 43 covers and Yandhi [V2] showed a
single's art. See docs/decisions.md::fetcher.py::art-tab-identity.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

import src.fetcher as fetcher


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


def test_oversized_image_is_refused_before_decode(monkeypatch):
    # The pixel cap is read from the header: a decompression bomb (tiny file, huge
    # canvas) must never be decoded. Lowered here so the test image stays small.
    monkeypatch.setattr(fetcher, "MAX_DECODE_PIXELS", 340 * 340 - 1)
    assert fetcher._dhash(_art(1, 340)) is None
    assert not fetcher.same_artwork(_art(1, 340), _art(1, 340))
