import Foundation
import SwiftUI
import Testing

@testable import LeakSheet

@Suite("Leak date parsing")
struct LeakDateParsingTests {
    // "MMM d, yyyy" is the dominant live format (86% of dated versions in
    // the 2026-07-20 TrackerHub sweep, incl. the entire Ye tracker); before
    // the fix it fell through to the bare-year regex and lost day precision.
    @Test func abbreviatedMonthDayParsesToFullPrecision() {
        let a = ArtistViewModel.parseLeakDate("Mar 20, 2023")
        let b = ArtistViewModel.parseLeakDate("Mar 21, 2023")
        #expect(a > 0)
        #expect(b - a == 86_400)  // day precision, not year-bucketed
    }

    @Test func fullMonthDayParses() {
        #expect(ArtistViewModel.parseLeakDate("March 20, 2023") ==
                ArtistViewModel.parseLeakDate("Mar 20, 2023"))
    }

    @Test func abbreviatedMonthYearParses() {
        let v = ArtistViewModel.parseLeakDate("Mar 2023")
        #expect(v == ArtistViewModel.parseLeakDate("March 2023"))
        #expect(v > 0)
    }

    @Test func irregularMonthDayShapesKeepDayPrecision() {
        let ref = ArtistViewModel.parseLeakDate("Sep 13, 1996")
        for raw in ["Sept 13, 1996", "Sept 13th, 1996", "Sep. 13, 1996", "Sep 13 1996",
                    "September 13th, 1996", "13 September 1996", "13th Sep 1996"] {
            #expect(ArtistViewModel.parseLeakDate(raw) == ref, "\(raw)")
        }
    }

    @Test func twoDigitYearSlashDates() {
        #expect(ArtistViewModel.parseLeakDate("03/20/23") == ArtistViewModel.parseLeakDate("03/20/2023"))
        #expect(ArtistViewModel.parseLeakDate("3/5/19") == ArtistViewModel.parseLeakDate("03/05/2019"))
    }

    @Test func existingFormatsStillParse() {
        #expect(ArtistViewModel.parseLeakDate("03/20/2023") > 0)
        #expect(ArtistViewModel.parseLeakDate("2023-03-20") > 0)
        #expect(ArtistViewModel.parseLeakDate("March 2023") > 0)
        #expect(ArtistViewModel.parseLeakDate("2023") > 0)
    }

    @Test func yearFallbackAndGarbage() {
        // Unknown format containing a year still year-buckets…
        #expect(ArtistViewModel.parseLeakDate("sometime in 2019?") > 0)
        // …and true garbage sorts to the bottom.
        #expect(ArtistViewModel.parseLeakDate("n/a") == 0)
        #expect(ArtistViewModel.parseLeakDate("") == 0)
    }

    // 2026-07-24: two forms the web reference parses (via Date.parse) that
    // iOS previously year-bucketed.
    @Test func iso8601WithTimeParsesToDayPrecision() {
        let a = ArtistViewModel.parseLeakDate("2023-03-20T14:30:00Z")
        let b = ArtistViewModel.parseLeakDate("2023-03-21T14:30:00Z")
        #expect(a > 0)
        #expect(b - a == 86_400)
    }

    @Test func dayFirstOrderingParsesToDayPrecision() {
        let a = ArtistViewModel.parseLeakDate("20 Mar 2023")
        #expect(a == ArtistViewModel.parseLeakDate("Mar 20, 2023"))
    }

    // DateFormatter is lenient enough to accept these two without dedicated
    // formatters — pinned so a future formatter change can't silently
    // regress them to year-bucketing.
    @Test func leniencyAcceptedFormsKeepDayPrecision() {
        #expect(ArtistViewModel.parseLeakDate("Mar 20 2023") ==
                ArtistViewModel.parseLeakDate("Mar 20, 2023"))
        #expect(ArtistViewModel.parseLeakDate("2023/03/20") ==
                ArtistViewModel.parseLeakDate("2023-03-20"))
    }
}

@Suite("Badge dedupe")
struct BadgeLogicTests {
    @Test func qualityIsPrimaryWhenMeaningful() {
        let p = BadgeLogic.primaryPill(quality: "CD Quality", availability: "Full")
        #expect(p == BadgeLogic.Pill(text: "CD Quality", isQuality: true))
    }

    @Test(arguments: ["", "Not Available", "n/a", "N/A"])
    func availabilityStandsInWhenQualityIsEmptyOrNA(_ quality: String) {
        let p = BadgeLogic.primaryPill(quality: quality, availability: "Snippet")
        #expect(p == BadgeLogic.Pill(text: "Snippet", isQuality: false))
    }

    @Test func noPillWhenBothAreEmptyOrNA() {
        #expect(BadgeLogic.primaryPill(quality: nil, availability: nil) == nil)
        #expect(BadgeLogic.primaryPill(quality: "N/A", availability: "n/a") == nil)
    }

    @Test func availabilityPillSuppressedWhenItDuplicatesQuality() {
        #expect(BadgeLogic.availabilityPill(quality: "OG File", availability: "OG File") == nil)
    }

    @Test func availabilityPillSuppressedWhenItAddsNothing() {
        // Not in the informative whitelist — the quality pill already says it.
        #expect(BadgeLogic.availabilityPill(quality: "CD Quality", availability: "Yes") == nil)
        #expect(BadgeLogic.availabilityPill(quality: "CD Quality", availability: "n/a") == nil)
    }

    @Test func availabilityPillShownWhenItAddsInformation() {
        let p = BadgeLogic.availabilityPill(quality: "CD Quality", availability: "Snippet")
        #expect(p == BadgeLogic.Pill(text: "Snippet", isQuality: false))
    }

    @Test func availabilityPillSuppressedWhenNoQualityPillIsShown() {
        // Availability already took the primary slot — don't render it twice.
        #expect(BadgeLogic.availabilityPill(quality: "", availability: "Full") == nil)
    }

    // Regression: Ye "Hurricane" in DONDA [V3] carries worst, special AND
    // plain versions. Its song-level badge is 'worst' (first badged version
    // wins server-side), so filtering to Best Of kept the ✨ version but the
    // row still displayed 🗑️.
    @Test func filteredRowTakesItsBadgeFromTheKeptVersions() {
        func v(_ tag: String, _ badge: String?) -> SongVersion {
            SongVersion(
                name: "Hurricane", versionTag: tag, badge: badge, featuring: nil,
                producers: nil, collaboration: nil, refs: nil, director: nil, creditedArtists: nil,
                altTitles: nil, notes: nil, ogFilename: nil, ogFilenames: nil,
                samples: nil, trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
                availableLength: "Full", quality: "CD Quality", streaming: nil,
                links: nil, dateOfRecording: nil, type: nil, sources: nil, rating: nil
            )
        }
        let song = Song(
            baseName: "Hurricane", songKey: "hurricane",
            versions: [v("V78", "worst"), v("V99", "special"), v("V101", nil)],
            badge: "worst"
        )
        let bestOf = song.withFilteredVersions { $0.badge == "special" || $0.badge == "best" }
        #expect(bestOf?.computedBadge == .special)

        let worstOf = song.withFilteredVersions { $0.badge == "worst" }
        #expect(worstOf?.computedBadge == .worst)

        // A filter that keeps only unbadged versions still reports the song's
        // own badge — the song IS badged, just not on these rows.
        let plain = song.withFilteredVersions { $0.badge == nil }
        #expect(plain?.computedBadge == .worst)
    }

    @Test func mostSignificantPrefersPositiveBadges() {
        func v(_ badge: String?) -> SongVersion {
            SongVersion(
                name: "x", versionTag: nil, badge: badge, featuring: nil,
                producers: nil, collaboration: nil, refs: nil, director: nil, creditedArtists: nil,
                altTitles: nil, notes: nil, ogFilename: nil, ogFilenames: nil,
                samples: nil, trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
                availableLength: nil, quality: nil, streaming: nil, links: nil,
                dateOfRecording: nil, type: nil, sources: nil, rating: nil
            )
        }
        #expect(Badge.mostSignificant(in: [v("worst"), v("best")]) == .best)
        #expect(Badge.mostSignificant(in: [v("ai"), v("grail"), v("best")]) == .grail)
        #expect(Badge.mostSignificant(in: [v(nil), v(nil)]) == nil)
    }

    @Test func britishRumouredSpellingIsClassified() {
        // 8 real occurrences in the census data fell through to the default
        // style before the "rumo" prefix match.
        #expect(availabilityVariant("Rumoured") == .rumored)
        #expect(availabilityVariant("Rumored") == .rumored)
    }
}
