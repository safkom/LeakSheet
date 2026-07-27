import Foundation
import Testing

@testable import LeakSheet

private func version(_ name: String, tag: String? = nil) -> SongVersion {
    SongVersion(
        name: name, versionTag: tag, badge: nil, featuring: nil, producers: nil,
        collaboration: nil, refs: nil, creditedArtists: nil, altTitles: nil, notes: nil, ogFilename: nil,
        ogFilenames: nil, samples: nil, trackLength: nil, fileDate: nil, leakDate: nil,
        availableLength: nil, quality: nil, streaming: nil, links: nil, dateOfRecording: nil, type: nil, sources: nil, rating: nil
    )
}

private func entry(
    artist: String, era: String, song: String, addedAt: Date
) -> FavouritesManager.FavouriteEntry {
    FavouritesManager.FavouriteEntry(
        key: FavouritesManager.key(artistSlug: artist, eraName: era, baseName: song),
        artistSlug: artist, artistName: artist.capitalized, sourceUrl: nil,
        eraName: era, eraArt: nil, songBaseName: song, songVersionCount: 1,
        badge: nil, addedAt: addedAt, primaryVersion: nil, primaryVersionName: nil,
        primaryVersionTag: nil, links: nil, quality: nil, availableLength: nil,
        notes: nil, trackLength: nil, leakDate: nil
    )
}

struct DerivedBaseNameTests {
    @Test(arguments: [
        ("Hurricane [V4]", "V4", "Hurricane"),
        ("Hurricane", nil, "Hurricane"),
        ("New Body [Alt.]", "Alt.", "New Body"),
        ("Time Moves Slow [V1-V3]", "V1-V3", "Time Moves Slow"),
        ("Runaway [v2]", "V2", "Runaway"),          // tag case difference
        ("Flashing Lights [V2] ", "V2", "Flashing Lights"),  // trailing space
        ("No Tag Here", "V9", "No Tag Here"),        // tag not in the name
    ] as [(String, String?, String)])
    func `strips the version tag like the parser's base_name`(
        name: String, tag: String?, expected: String
    ) {
        #expect(version(name, tag: tag).derivedBaseName == expected)
    }
}

struct FavouritesGroupingTests {
    private let t0 = Date(timeIntervalSince1970: 1_000_000)

    @Test func `grouping is deterministic and ordered by recency`() {
        let entries = [
            entry(artist: "ye", era: "Donda", song: "Jail", addedAt: t0 + 30),
            entry(artist: "carti", era: "WLR", song: "Cancun", addedAt: t0 + 20),
            entry(artist: "ye", era: "Yeezus", song: "Bound", addedAt: t0 + 10),
        ]
        let grouped = FavouritesManager.grouped(from: entries)

        // Artists newest-first: ye (t0+30) before carti (t0+20).
        #expect(grouped.map(\.artistSlug) == ["ye", "carti"])
        // Eras within ye newest-first: Donda before Yeezus.
        #expect(grouped[0].eras.map(\.eraName) == ["Donda", "Yeezus"])

        // Recomputing over the same input must give the identical order —
        // the old dictionary-based grouping shuffled between calls.
        for _ in 0..<10 {
            let again = FavouritesManager.grouped(from: entries)
            #expect(again.map(\.artistSlug) == grouped.map(\.artistSlug))
            #expect(again[0].eras.map(\.eraName) == grouped[0].eras.map(\.eraName))
        }
    }

    @Test func `entries stay in stored order within an era`() {
        let entries = [
            entry(artist: "ye", era: "Donda", song: "Newest", addedAt: t0 + 2),
            entry(artist: "ye", era: "Donda", song: "Older", addedAt: t0 + 1),
        ]
        let grouped = FavouritesManager.grouped(from: entries)
        #expect(grouped[0].eras[0].entries.map(\.songBaseName) == ["Newest", "Older"])
    }
}
