import Foundation
import Testing

@testable import LeakSheet

private func version(_ name: String, tag: String? = nil) -> SongVersion {
    SongVersion(
        name: name, versionTag: tag, badge: nil, featuring: nil, producers: nil,
        collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: nil, notes: nil, ogFilename: nil,
        ogFilenames: nil, samples: nil, trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
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

/// The 2026-08 version-tag widening changed `Song.baseName` for rows whose
/// title carried a Demo / OG File / Instrumental / … tag. Favourites are keyed
/// on that name, so entries saved before the change stopped matching their row
/// and the heart silently went cold.
@Suite("Favourite version-tag migration")
struct FavouriteTagMigrationTests {
    private func stored(_ song: String, era: String = "Era", artist: String = "ye") -> FavouritesManager.FavouriteEntry {
        entry(artist: artist, era: era, song: song, addedAt: Date(timeIntervalSince1970: 0))
    }

    @Test(arguments: [
        ("90210 [Demo 8]", "90210"),
        ("Track [Demo]", "Track"),
        ("Track [OG File]", "Track"),
        ("Track [Instrumental]", "Track"),
        ("Track [Final Mix 2]", "Track"),
        ("Track [Mix A]", "Track"),
        ("Track [Live]", "Track"),
    ])
    func `an orphaned tag is stripped from the key`(oldName: String, newName: String) {
        let migrated = FavouritesManager.migratingVersionTags([stored(oldName)])
        #expect(migrated[0].songBaseName == newName)
        #expect(migrated[0].key == FavouritesManager.key(artistSlug: "ye", eraName: "Era", baseName: newName))
    }

    @Test(arguments: ["Track [Mixtape]", "Track [Deluxe]", "Track [V1]", "Track [2019]", "Track"])
    func `names the widening did not affect are left alone`(name: String) {
        let migrated = FavouritesManager.migratingVersionTags([stored(name)])
        #expect(migrated[0].songBaseName == name)
        #expect(migrated[0].key == stored(name).key)
    }

    /// Two versions of one song favourited separately would collapse onto the
    /// same key; keep the second as-is rather than create a duplicate.
    @Test func `a collision leaves the later entry untouched`() {
        let migrated = FavouritesManager.migratingVersionTags([
            stored("90210 [Demo 8]"),
            stored("90210 [Demo 9]"),
        ])
        #expect(migrated[0].songBaseName == "90210")
        #expect(migrated[1].songBaseName == "90210 [Demo 9]")
        #expect(Set(migrated.map(\.key)).count == 2, "keys must stay unique")
    }

    @Test func `a bare tag is not stripped down to an empty name`() {
        let migrated = FavouritesManager.migratingVersionTags([stored("[Demo 8]")])
        #expect(migrated[0].songBaseName == "[Demo 8]")
    }

    @Test func `entries in different eras migrate independently`() {
        let migrated = FavouritesManager.migratingVersionTags([
            stored("90210 [Demo 8]", era: "Era A"),
            stored("90210 [Demo 8]", era: "Era B"),
        ])
        #expect(migrated.allSatisfy { $0.songBaseName == "90210" })
        #expect(Set(migrated.map(\.key)).count == 2)
    }
}

/// The badge row on a favourites entry.
@Suite("Favourite badge source")
struct FavouriteBadgeSourceTests {
    /// New writes leave the flat quality/availableLength fields nil — they are
    /// the pre-snapshot legacy path — so reading them alone rendered a blank
    /// badge row for every favourite added since the primaryVersion migration.
    @Test func `pills come from the version snapshot when the flat fields are nil`() {
        let v = SongVersion(
            name: "Track", versionTag: nil, badge: nil, featuring: nil, producers: nil,
            collaboration: nil, refs: nil, director: nil, creditedArtists: nil,
            altTitles: nil, notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil, availableLength: "Full",
            quality: "Lossless", streaming: nil, links: nil, dateOfRecording: nil,
            type: nil, sources: nil, rating: nil
        )
        let entry = FavouritesManager.FavouriteEntry(
            key: "k", artistSlug: "a", artistName: "A", sourceUrl: nil,
            eraName: "E", eraArt: nil, songBaseName: "Track", songVersionCount: 1,
            badge: nil, addedAt: Date(), primaryVersion: v,
            primaryVersionName: nil, primaryVersionTag: nil, links: nil,
            quality: nil, availableLength: nil, notes: nil, trackLength: nil, leakDate: nil
        )
        // What FavouritesView renders from.
        #expect((entry.primaryVersion?.quality ?? entry.quality) == "Lossless")
        #expect((entry.primaryVersion?.availableLength ?? entry.availableLength) == "Full")
        // And the pill logic actually produces something for those values.
        #expect(BadgeLogic.primaryPill(quality: "Lossless", availability: "Full") != nil)
    }

    @Test func `entries predating the snapshot still read their flat fields`() {
        let entry = FavouritesManager.FavouriteEntry(
            key: "k", artistSlug: "a", artistName: "A", sourceUrl: nil,
            eraName: "E", eraArt: nil, songBaseName: "Track", songVersionCount: 1,
            badge: nil, addedAt: Date(), primaryVersion: nil,
            primaryVersionName: "Track", primaryVersionTag: nil, links: nil,
            quality: "CD Quality", availableLength: "Snippet", notes: nil,
            trackLength: nil, leakDate: nil
        )
        #expect((entry.primaryVersion?.quality ?? entry.quality) == "CD Quality")
    }
}
