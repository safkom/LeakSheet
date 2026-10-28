from src.fetcher import _OTHER_CONTENT_TAB_NAMES, _clean_tab_name, _get_art_tab_gid, _get_unreleased_tab_gid


def test_wip_edits_tab_matches_other_content_names():
    assert _clean_tab_name("Edits (WIP)") in _OTHER_CONTENT_TAB_NAMES


def test_unqualified_tab_beats_qualified_regardless_of_order():
    tabs = {"1": "Unreleased (Old)", "2": "Unreleased"}
    assert _get_unreleased_tab_gid(tabs) == "2"
    assert _get_art_tab_gid({"1": "Art (old)", "2": "🎨 Art"}) == "2"


def test_qualified_tab_still_used_when_alone():
    assert _get_unreleased_tab_gid({"1": "Unreleased (WIP)"}) == "1"


def test_gid_fetch_slot_survives_a_second_event_loop():
    import asyncio

    from src.fetcher import _gid_fetch_slot

    async def use():
        async with _gid_fetch_slot():
            return True

    assert asyncio.run(use())
    assert asyncio.run(use())


def test_tab_discovery_handles_escaped_quote_in_name():
    from src.fetcher import _discover_page_urls, _discover_named_tabs

    html = r'items.push({name: "Say \"Hi\"", pageUrl: "\/htmlview\/sheet\/55.html", gid: "55"});'
    assert _discover_named_tabs(html) == {"55": 'Say "Hi"'}
    assert _discover_page_urls(html)["55"][0] == 'Say "Hi"'


def test_new_qualified_tab_beats_plain_name():
    # The plain tab is the stale one when the tracker marks a successor as new.
    for new in ("Unreleased [NEW]", "Unreleased (NEW)", "Unreleased (Updated)", "Unreleased [2.0]"):
        assert _get_unreleased_tab_gid({"1": "Unreleased", "2": new}) == "2", new
        assert _get_unreleased_tab_gid({"2": new, "1": "Unreleased"}) == "2", new


def test_stale_qualified_tab_loses_to_any_other_candidate():
    for stale in ("Unreleased (Archive)", "Unreleased [Archived]", "Unreleased (OUTDATED)", "Unreleased (Old)",
                  "Unreleased (Backup)", "Unreleased (Deprecated)"):
        assert _get_unreleased_tab_gid({"1": stale, "2": "Unreleased (WIP)"}) == "2", stale
        assert _get_unreleased_tab_gid({"1": stale, "2": "Unreleased"}) == "2", stale


def test_beatles_layout_picks_the_new_tab():
    tabs = {"10": "Unreleased", "11": "Unreleased [NEW]", "12": "Unreleased (Archive)", "13": "Released"}
    assert _get_unreleased_tab_gid(tabs) == "11"


def test_stale_tab_still_used_when_alone():
    assert _get_unreleased_tab_gid({"1": "Unreleased (Archive)"}) == "1"


def test_new_must_be_the_whole_qualifier():
    # "(New Leaks)" is a subset of the catalogue, not its successor.
    assert _get_unreleased_tab_gid({"1": "Unreleased", "2": "Unreleased (New Leaks)"}) == "1"
    assert _get_unreleased_tab_gid({"1": "Unreleased", "2": "Unreleased (NEW!)"}) == "2"


def test_version_one_is_not_newer_than_plain():
    assert _get_unreleased_tab_gid({"1": "Unreleased (1.0)", "2": "Unreleased"}) == "2"
    assert _get_unreleased_tab_gid({"1": "Unreleased (v1)", "2": "Unreleased"}) == "2"
    assert _get_unreleased_tab_gid({"1": "Unreleased", "2": "Unreleased (v2)"}) == "2"


def test_unspaced_slash_name_counts_as_plain():
    tabs = {"1": "Unreleased (Notes)", "2": "Unreleased/Off-Streaming"}
    assert _get_unreleased_tab_gid(tabs) == "2"
