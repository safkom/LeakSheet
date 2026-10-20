from src.models import Badge, extract_badge, parse_song_credits


def test_stacked_badge_emojis_all_stripped_best_priority_wins():
    badge, name = extract_badge("🏆🥇 Song [V1]")
    assert badge == Badge.GRAIL
    assert name == "Song [V1]"


def test_stacked_badges_priority_not_order():
    badge, name = extract_badge("🥇 ⭐ Song")
    assert badge == Badge.BEST
    assert name == "Song"


def test_decorative_between_badges():
    badge, name = extract_badge("🥇💿🏆 Song")
    assert (badge, name) == (Badge.GRAIL, "Song")


def test_nested_paren_credit_keeps_producer():
    c = parse_song_credits("Song\n(feat. A (prod. B))")
    assert c.featuring == "A"
    assert c.producers == "B"
    assert c.alt_titles == []


def test_nested_paren_inline_with_title():
    c = parse_song_credits("Song (feat. A (prod. B)) [V1]")
    assert c.title.startswith("Song")
    assert c.producers == "B"


def test_ai_marker_survives_a_stacked_better_badge():
    badge, name = extract_badge("⭐🤖 Song [V2]")
    assert badge == Badge.AI
    assert name == "Song [V2]"


def test_ai_marker_wins_over_grail_when_stacked():
    assert extract_badge("🏆🤖 Song")[0] == Badge.AI
