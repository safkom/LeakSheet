import Foundation
import SwiftUI
import Testing

@testable import LeakSheet

/// Content-tab groups must read in the artist's own era order.
///
/// Grouping alone emitted groups in sheet-row order, which put whatever the
/// tab listed first at the top: on the Ye Misc tab that was "Opt Archive",
/// "Twitter" and "Pierre-Louis Auvray" — 4 entries of 747, each a source name
/// the sheet happened to put in its Era column — above every real era.
@Suite("Tab entry identity")
struct MiscEntryIdentityTests {
    private func beat(_ row: Int?) -> MiscEntry {
        MiscEntry(
            eraName: "Before The College Dropout", rowIndex: row, name: "Beat 1",
            notes: nil, entryType: nil, date: nil, length: nil, available: nil,
            quality: nil, streaming: nil, links: [], sourceTab: "stems"
        )
    }

    @Test("identical rows keep distinct ids")
    func identicalRowsAreDistinct() {
        // The Ye Stems tab lists ten entries called "Beat 1" in one era with
        // no date. ForEach keeps only the first row per duplicate id, so 458
        // of its 1,721 rows never rendered while the stats bar counted them.
        let rows = (0..<10).map { beat($0) }
        #expect(Set(rows.map(\.id)).count == 10)
    }

    @Test("a row is found by its own id, not a twin's")
    func lookupFindsTheRightRow() {
        let rows = (0..<10).map { beat($0) }
        #expect(rows.firstIndex(where: { $0.id == rows[4].id }) == 4)
    }

    @Test("payloads cached before the index existed still decode and group")
    func legacyPayloadFallsBack() {
        let legacy = beat(nil)
        #expect(legacy.id == "stems::Before The College Dropout::Beat 1::")
    }
}

@Suite("Misc era grouping")
struct MiscEraGroupingTests {
    private func entry(_ name: String, era: String, row: Int = 0) -> MiscEntry {
        MiscEntry(
            eraName: era, rowIndex: row, name: name, notes: nil, entryType: nil, date: nil,
            length: nil, available: nil, quality: nil, streaming: nil,
            links: [], sourceTab: "misc"
        )
    }

    @Test("groups follow era order, not sheet order")
    func groupsFollowEraOrder() {
        let entries = [
            entry("c", era: "Graduation"),
            entry("a", era: "The College Dropout"),
            entry("b", era: "Late Registration")
        ]
        let groups = ArtistViewModel.groupMiscByEra(
            entries,
            eraOrder: ["The College Dropout", "Late Registration", "Graduation"]
        )
        #expect(groups.map(\.eraName) == ["The College Dropout", "Late Registration", "Graduation"])
    }

    @Test("unmatched groups keep their content and sort last")
    func unmatchedGroupsSortLast() {
        let entries = [
            entry("tweet", era: "Twitter"),
            entry("song", era: "Graduation"),
            entry("art", era: "Opt Archive")
        ]
        let groups = ArtistViewModel.groupMiscByEra(
            entries, eraOrder: ["Graduation"]
        )
        #expect(groups.map(\.eraName) == ["Graduation", "Twitter", "Opt Archive"])
        // Nothing may be dropped — these are real entries, just not eras.
        #expect(groups.flatMap(\.entries).count == 3)
    }

    @Test("era column casing and stray whitespace still match")
    func looseMatching() {
        let entries = [entry("x", era: "  graduation ")]
        let groups = ArtistViewModel.groupMiscByEra(entries, eraOrder: ["Graduation"])
        #expect(groups.count == 1)
        #expect(groups[0].entries.count == 1)
    }

    @Test("no era order given falls back to sheet order")
    func fallbackKeepsSheetOrder() {
        let entries = [entry("a", era: "Z"), entry("b", era: "A")]
        let groups = ArtistViewModel.groupMiscByEra(entries)
        #expect(groups.map(\.eraName) == ["Z", "A"])
    }
}
