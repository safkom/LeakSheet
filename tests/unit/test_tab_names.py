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

    assert asyncio.run(use()) and asyncio.run(use())


def test_tab_discovery_handles_escaped_quote_in_name():
    from src.fetcher import _discover_page_urls, _discover_named_tabs

    html = r'items.push({name: "Say \"Hi\"", pageUrl: "\/htmlview\/sheet\/55.html", gid: "55"});'
    assert _discover_named_tabs(html) == {"55": 'Say "Hi"'}
    assert _discover_page_urls(html)["55"][0] == 'Say "Hi"'
