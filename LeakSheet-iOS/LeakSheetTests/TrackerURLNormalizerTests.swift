import Foundation
import Testing

@testable import LeakSheet

struct TrackerURLNormalizerTests {
    private static let canonical =
        "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/htmlview"

    @Test(arguments: [
        "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit#gid=0",
        "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit?usp=sharing",
        "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/view",
        "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/htmlview#gid=123",
        "https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/htmlview/sheet?headers=true&gid=1",
        "https://docs.google.com/spreadsheets/u/0/d/1AbC_d-42xYz/htmlview",
        "http://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit",
        "docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit",
        "  https://docs.google.com/spreadsheets/d/1AbC_d-42xYz/edit  ",
        "HTTPS://DOCS.GOOGLE.COM/spreadsheets/d/1AbC_d-42xYz/edit",
    ])
    func `google sheet URL variants collapse to the htmlview form`(url: String) {
        #expect(TrackerURLNormalizer.normalize(url) == Self.canonical)
    }

    @Test(arguments: [
        "yetracker.net",
        "https://yetracker.net",
        "https://yetracker.net/",
        "yetracker.net/#top",
        "HTTPS://YETRACKER.NET/",
    ])
    func `bare host variants collapse to the trailing-slash form`(url: String) {
        #expect(TrackerURLNormalizer.normalize(url) == "https://yetracker.net/")
    }

    @Test func `distinct sheet ids stay distinct`() {
        let a = TrackerURLNormalizer.normalize("https://docs.google.com/spreadsheets/d/AAA/edit")
        let b = TrackerURLNormalizer.normalize("https://docs.google.com/spreadsheets/d/BBB/edit")
        #expect(a != b)
    }

    @Test func `distinct non-google paths stay distinct`() {
        let root = TrackerURLNormalizer.normalize("https://yetracker.net/")
        let sub = TrackerURLNormalizer.normalize("https://yetracker.net/other")
        #expect(root != sub)
    }

    @Test func `non-google query strings are preserved`() {
        let url = TrackerURLNormalizer.normalize("https://example.com/a?b=1")
        #expect(url == "https://example.com/a?b=1")
    }

    @Test func `normalization is stable for unparseable input`() {
        let junk = "not a url at all"
        #expect(TrackerURLNormalizer.normalize(junk) == TrackerURLNormalizer.normalize(junk))
        #expect(!TrackerURLNormalizer.normalize(junk).isEmpty)
        #expect(TrackerURLNormalizer.normalize("") == "")
    }
}

struct RecentTrackerDedupTests {
    private func entry(url: String, slug: String = "x", name: String = "X") -> RecentTrackersManager.RecentTracker {
        RecentTrackersManager.RecentTracker(
            name: name, slug: slug, sourceUrl: url, totalSongs: 0,
            artUrl: nil, availableCount: 0, snippetCount: 0, confirmedCount: 0
        )
    }

    @Test func `saved name is found across url variants and is nil when unknown`() {
        // The backend derives the artist slug from the name it is given, and
        // favourites are keyed on that slug — so reopening a tracker must reuse
        // the name it was first opened under, even when the URL is a variant.
        let saved = entry(
            url: "https://docs.google.com/spreadsheets/d/AAA/htmlview",
            slug: "billie-eilish-alt-3", name: "Billie Eilish [Alt #3]"
        )
        let variant = "https://docs.google.com/spreadsheets/d/AAA/edit?usp=sharing"

        #expect(RecentTrackersManager.savedName(forSourceUrl: variant, in: [saved]) == "Billie Eilish [Alt #3]")
        #expect(RecentTrackersManager.savedName(forSourceUrl: "https://docs.google.com/spreadsheets/d/BBB/htmlview", in: [saved]) == nil)
        #expect(RecentTrackersManager.savedName(forSourceUrl: "  ", in: [saved]) == nil)
    }

    @Test func `url variants of the same tracker collapse keeping the newest`() {
        let newest = entry(url: "https://docs.google.com/spreadsheets/d/AAA/htmlview", name: "New")
        let older = entry(url: "https://docs.google.com/spreadsheets/d/AAA/edit?usp=sharing", name: "Old")
        let other = entry(url: "https://docs.google.com/spreadsheets/d/BBB/htmlview")
        let result = RecentTrackersManager.deduplicated([newest, older, other])
        #expect(result.count == 2)
        #expect(result.first?.name == "New")
    }

    @Test func `entries without a url fall back to slug identity`() {
        let a = entry(url: "", slug: "artist-a")
        let b = entry(url: "", slug: "artist-b")
        let aDup = entry(url: "", slug: "artist-a")
        let result = RecentTrackersManager.deduplicated([a, b, aDup])
        #expect(result.count == 2)
    }

    @Test func `cap is enforced after dedup`() {
        let entries = (0..<30).map { entry(url: "https://yetracker.net/\($0)") }
        #expect(RecentTrackersManager.deduplicated(entries).count == 20)
        #expect(RecentTrackersManager.deduplicated(entries, cap: 5).count == 5)
    }

}
