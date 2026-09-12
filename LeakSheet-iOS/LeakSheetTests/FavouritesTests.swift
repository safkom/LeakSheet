import Foundation
import Testing

@testable import LeakSheet

private func version(_ name: String, tag: String? = nil, link: String? = nil) -> SongVersion {
    SongVersion(
        name: name, versionTag: tag, badge: nil, featuring: nil, producers: nil,
        collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: nil, notes: nil, ogFilename: nil,
        ogFilenames: nil, samples: nil, trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
        availableLength: nil, quality: nil, streaming: nil, links: link.map { [$0] }, dateOfRecording: nil, type: nil, sources: nil, rating: nil
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


/// Placeholder favourites (2026-08-26).
///
/// "???" is how these trackers write "nobody knows what this is", and one era
/// carries dozens. Keying on artist + era + name gave all of them the same
/// key: 282 Ye songs collided, so favouriting one filled the heart on every
/// other unidentified track in that era.
@Suite("Placeholder favourite identity")
struct PlaceholderFavouriteKeyTests {
    @Test("two unidentified tracks in one era get different keys")
    func distinctKeys() {
        let a = FavouritesManager.key(
            artistSlug: "ye", eraName: "God's Country", baseName: "???",
            discriminator: FavouritesManager.discriminator(for: version("???", link: "https://pillows.su/f/a"))
        )
        let b = FavouritesManager.key(
            artistSlug: "ye", eraName: "God's Country", baseName: "???",
            discriminator: FavouritesManager.discriminator(for: version("???", link: "https://pillows.su/f/b"))
        )
        #expect(a != b)
    }

    @Test(arguments: ["???", "??", "?", "Unknown", "untitled", "TBA", "n/a"])
    func `every placeholder spelling is discriminated`(name: String) {
        let plain = FavouritesManager.key(artistSlug: "ye", eraName: "E", baseName: name)
        let keyed = FavouritesManager.key(
            artistSlug: "ye", eraName: "E", baseName: name, discriminator: "https://x/1"
        )
        #expect(plain != keyed)
    }

    @Test("a real title's key is byte-identical to before, so nothing migrates")
    func realTitlesUnchanged() {
        #expect(
            FavouritesManager.key(
                artistSlug: "ye", eraName: "DONDA", baseName: "Hurricane",
                discriminator: "https://pillows.su/f/a"
            ) == "ye::DONDA::Hurricane"
        )
    }

    @Test("a placeholder with no link keeps the undiscriminated key")
    func noLinkNoDiscriminator() {
        #expect(
            FavouritesManager.key(
                artistSlug: "ye", eraName: "E", baseName: "???",
                discriminator: FavouritesManager.discriminator(for: version("???"))
            ) == "ye::E::???"
        )
    }

    @Test("stored placeholder entries are re-keyed onto their file")
    func migration() {
        func stored(_ link: String?) -> FavouritesManager.FavouriteEntry {
            FavouritesManager.FavouriteEntry(
                key: "ye::God's Country::???",
                artistSlug: "ye", artistName: "Ye", sourceUrl: nil,
                eraName: "God's Country", eraArt: nil, songBaseName: "???",
                songVersionCount: 1, badge: nil, addedAt: Date(),
                primaryVersion: version("???", link: link), primaryVersionName: nil,
                primaryVersionTag: nil, links: nil, quality: nil,
                availableLength: nil, notes: nil, trackLength: nil, leakDate: nil
            )
        }
        let migrated = FavouritesManager.migratingPlaceholderKeys(
            [stored("https://pillows.su/f/a"), stored("https://pillows.su/f/b"), stored(nil)]
        )
        #expect(migrated[0].key == "ye::God's Country::???::https://pillows.su/f/a")
        #expect(migrated[1].key == "ye::God's Country::???::https://pillows.su/f/b")
        // Nothing to tell it apart by — left alone rather than guessed at.
        #expect(migrated[2].key == "ye::God's Country::???")
        #expect(Set(migrated.map(\.key)).count == 3)
    }
}

/// Now-playing row identity (2026-08-26).
@MainActor
@Suite("Now playing row identity")
struct NowPlayingIdentityTests {
    private func v(_ name: String, tag: String? = nil, link: String) -> SongVersion {
        version(name, tag: tag, link: link)
    }

    /// Drives the shared engine directly: PlayerViewModel is a facade over it,
    /// and the predicate under test reads only currentTrack and eraName.
    private func withPlaying(
        _ track: SongVersion, era: String, _ body: (PlayerViewModel) -> Void
    ) {
        let engine = AudioEngine.shared
        let savedTrack = engine.currentTrack
        let savedEra = engine.eraName
        engine.currentTrack = track
        engine.eraName = era
        body(PlayerViewModel.shared)
        engine.currentTrack = savedTrack
        engine.eraName = savedEra
    }

    @Test("two unidentified tracks in one era do not both light up")
    func placeholdersInOneEra() {
        let playing = v("???", link: "https://pillows.su/f/a")
        let other = v("???", link: "https://pillows.su/f/b")
        withPlaying(playing, era: "God's Country") { player in
            #expect(player.isNowPlaying(playing, inEra: "God's Country"))
            #expect(!player.isNowPlaying(other, inEra: "God's Country"))
        }
    }

    @Test("the same song in another era does not light up")
    func sameNameOtherEra() {
        let playing = v("Hurricane", tag: "V4", link: "https://pillows.su/f/a")
        let twin = v("Hurricane", tag: "V4", link: "https://pillows.su/f/z")
        withPlaying(playing, era: "DONDA [V1]") { player in
            #expect(player.isNowPlaying(playing, inEra: "DONDA [V1]"))
            #expect(!player.isNowPlaying(twin, inEra: "Donda [V2]"))
        }
    }

    @Test("a row with no era still resolves — misc entries carry none")
    func emptyEraIsNotAMismatch() {
        let playing = v("Some Video", link: "https://youtu.be/x")
        withPlaying(playing, era: "") { player in
            #expect(player.isNowPlaying(playing, inEra: ""))
        }
    }

    @Test("nothing playing means no row is playing")
    func nothingPlaying() {
        let engine = AudioEngine.shared
        let saved = engine.currentTrack
        engine.currentTrack = nil
        #expect(!PlayerViewModel.shared.isNowPlaying(v("X", link: "https://x/1"), inEra: "E"))
        engine.currentTrack = saved
    }
}
