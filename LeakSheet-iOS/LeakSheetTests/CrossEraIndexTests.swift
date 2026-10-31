import Foundation
import SwiftUI
import Testing

@testable import LeakSheet

/// Cross-era song linkage (2026-07-18): Precomputed indexes songKey → eras.
struct CrossEraIndexTests {
    private func song(_ name: String, key: String?, versions: Int = 1) -> Song {
        let v = SongVersion(
            name: name, versionTag: nil, badge: nil, featuring: nil,
            producers: nil, collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: nil,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
            availableLength: "Full", quality: nil, streaming: nil, links: nil,
            dateOfRecording: nil, type: nil, sources: nil, rating: nil
        )
        return Song(
            baseName: name, songKey: key,
            versions: Array(repeating: v, count: versions), badge: nil
        )
    }

    private func era(_ name: String, songs: [Song]) -> Era {
        Era(
            name: name, altNames: nil, description: nil, timeline: nil,
            artUrl: nil,
            sections: [Section(name: "", group: nil, songs: songs)],
            songCount: nil, versionCount: nil
        )
    }

    @Test func `index keeps only keys spanning multiple eras`() async {
        let artist = Artist(
            name: "T", slug: "t", sourceUrl: nil,
            eras: [
                era("War", songs: [song("This One Here", key: "this one here")]),
                era("Donda 2", songs: [
                    song("This One Here", key: "this one here", versions: 3),
                    song("Unique", key: "unique"),
                ]),
            ],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let vm = await MainActor.run { ArtistViewModel(artist: artist) }
        func payload(_ name: String, _ key: String?, era: String) -> DescriptionSheet.Payload {
            let s = song(name, key: key)
            return DescriptionSheet.Payload(
                song: s, version: s.versions[0],
                artistName: artist.name, artistSlug: artist.slug,
                eraName: era, eraArt: nil
            )
        }
        // A song in two eras resolves to both, current era first.
        let shared = await MainActor.run {
            vm.crossEraRefs(for: payload("This One Here", "this one here", era: "War"))
        }
        #expect(shared.map(\.eraName) == ["War", "Donda 2"])
        #expect(shared.last?.song.versions.count == 3)
        // An era-unique song resolves to exactly its own era — songKeyEras
        // drops single-era keys, so this exercises the base-name index.
        let unique = await MainActor.run {
            vm.crossEraRefs(for: payload("Unique", "unique", era: "Donda 2"))
        }
        #expect(unique.map(\.eraName) == ["Donda 2"])
    }

    @Test func `unidentified tracks are not linked to each other`() async {
        // "???" means "nobody knows what this is": each such row is its own track,
        // so the backend sends an empty songKey and the base-name fallback must not
        // group them (one key would list every unidentified track in one picker).
        let artist = Artist(
            name: "T", slug: "t", sourceUrl: nil,
            eras: [
                era("War", songs: [song("???", key: ""), song("???", key: "")]),
                era("Donda 2", songs: [song("???", key: ""), song("Real Song", key: "real song")]),
            ],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let vm = await MainActor.run { ArtistViewModel(artist: artist) }
        let placeholder = song("???", key: "")
        let payload = DescriptionSheet.Payload(
            song: placeholder, version: placeholder.versions[0],
            artistName: artist.name, artistSlug: artist.slug,
            eraName: "War", eraArt: nil
        )
        let refs = await MainActor.run { vm.crossEraRefs(for: payload) }
        #expect(refs.isEmpty)
        // The sheet still resolves to the song it was opened with.
        let resolved = await MainActor.run { vm.resolvedSong(for: payload) }
        #expect(resolved?.baseName == "???")
        #expect(resolved?.versions.count == 1)
    }

    @Test func `a payload with no song still refuses a placeholder name`() async {
        // Now Playing and Favourites carry a bare SongVersion, so the lookup
        // falls back to the version's derived base name — the same rule has to
        // hold there.
        let artist = Artist(
            name: "T", slug: "t", sourceUrl: nil,
            eras: [era("War", songs: [song("???", key: ""), song("Real Song", key: "real song")])],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let vm = await MainActor.run { ArtistViewModel(artist: artist) }
        let bare = song("???", key: "").versions[0]
        let payload = DescriptionSheet.Payload(
            song: nil, version: bare,
            artistName: artist.name, artistSlug: artist.slug,
            eraName: "War", eraArt: nil
        )
        #expect(await MainActor.run { vm.crossEraRefs(for: payload) }.isEmpty)

        // A real title still resolves through the base-name index.
        let real = song("Real Song", key: "real song").versions[0]
        let realPayload = DescriptionSheet.Payload(
            song: nil, version: real,
            artistName: artist.name, artistSlug: artist.slug,
            eraName: "War", eraArt: nil
        )
        #expect(await MainActor.run { vm.crossEraRefs(for: realPayload) }.map(\.eraName) == ["War"])
    }

    @Test func `resolved song keeps the full version set for description sheets`() async {
        let fullSong = song("This One Here", key: "this one here", versions: 2)
        let filteredSong = Song(
            baseName: fullSong.baseName,
            songKey: fullSong.songKey,
            versions: Array(fullSong.versions.prefix(1)),
            badge: fullSong.badge
        )
        let artist = Artist(
            name: "T", slug: "t", sourceUrl: nil,
            eras: [era("War", songs: [fullSong])],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let vm = await MainActor.run { ArtistViewModel(artist: artist) }
        let payload = DescriptionSheet.Payload(
            song: filteredSong,
            version: filteredSong.versions[0],
            artistName: artist.name,
            artistSlug: artist.slug,
            eraName: "War",
            eraArt: nil
        )
        let resolved = await MainActor.run { vm.resolvedSong(for: payload) }
        #expect(resolved?.versions.count == 2)
        #expect(resolved?.versions.contains(where: { $0.id == filteredSong.versions[0].id }) == true)
    }

    /// Now Playing and Favourites only hold a bare `SongVersion`, so their
    /// payloads carry `song: nil`. Both lookups used to bail on that, which is
    /// why the description sheet raised from the player's Info button showed no
    /// Versions picker, no alt title and only the playing version's credits.
    /// The version's own tag-stripped name is the base-name index's key.
    @Test func `a payload without a song resolves through the version's base name`() async {
        let fullSong = song("This One Here", key: "this one here", versions: 3)
        let artist = Artist(
            name: "T", slug: "t", sourceUrl: nil,
            eras: [era("War", songs: [fullSong])],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let vm = await MainActor.run { ArtistViewModel(artist: artist) }

        // Exactly the shape NowPlayingView builds: no song, one version, and
        // a name carrying the version tag the player displays.
        let bare = SongVersion(
            name: "This One Here [V2]", versionTag: "V2", badge: nil, featuring: nil,
            producers: nil, collaboration: nil, refs: nil, director: nil,
            creditedArtists: nil, altTitles: nil, notes: nil, ogFilename: nil,
            ogFilenames: nil, samples: nil, trackLength: nil, fileDate: nil,
            leakDate: nil, previewDate: nil, availableLength: "Full", quality: nil, streaming: nil,
            links: nil, dateOfRecording: nil, type: nil, sources: nil, rating: nil
        )
        let payload = DescriptionSheet.Payload(
            song: nil, version: bare,
            artistName: artist.name, artistSlug: artist.slug,
            eraName: "War", eraArt: nil
        )

        let refs = await MainActor.run { vm.crossEraRefs(for: payload) }
        #expect(refs.map(\.eraName) == ["War"])

        let resolved = await MainActor.run { vm.resolvedSong(for: payload) }
        // 3, not 1: the Versions section renders only when count > 1.
        #expect(resolved?.allVersions.count == 3)
        #expect(resolved?.baseName == "This One Here")
    }

    /// A badge filter must narrow what a row *shows* consistently: the count,
    /// the chevron and the expanded rows all read the same array. They used to
    /// disagree — the count came from `versions` (filtered) while expansion
    /// used `allVersions`, so a Best Of row read "1 versions" and then
    /// expanded to show a Rumored take the filter had excluded.
    @Test func `a badge filter narrows the row count and its expanded versions together`() async {
        func take(tag: String, badge: String?, available: String) -> SongVersion {
            SongVersion(
                name: "2Nite [\(tag)]", versionTag: tag, badge: badge, featuring: nil,
                producers: nil, collaboration: nil, refs: nil, director: nil,
                creditedArtists: nil, altTitles: nil, notes: nil, ogFilename: nil,
                ogFilenames: nil, samples: nil, trackLength: nil, fileDate: nil,
                leakDate: nil, previewDate: nil, availableLength: available, quality: "High Quality",
                streaming: nil, links: ["https://pillows.su/f/abc123"],
                dateOfRecording: nil, type: nil, sources: nil, rating: nil
            )
        }
        let rumored = take(tag: "V1", badge: nil, available: "Rumored")
        let starred = take(tag: "V2", badge: "best", available: "Full")
        let full = Song(baseName: "2Nite", songKey: nil, versions: [rumored, starred], badge: nil)
        let artist = Artist(
            name: "K", slug: "k", sourceUrl: nil,
            eras: [era("Era A", songs: [full])],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let filtered = ArtistViewModel.computeContent(
            artist: artist,
            state: FilterState(bestOf: true),
            eraStats: [:]
        )
        let song = try! #require(filtered.eras.first?.songs.first)

        // One version matched, so the row is a single-version row…
        #expect(song.versions.count == 1)
        #expect(song.versions.first?.versionTag == "V2")
        #expect(song.hasMultipleVersions == false)
        // …while the unfiltered set is still intact for playback and Details.
        #expect(song.allVersions.count == 2)
    }

    @Test func `a payload with no song and no match still returns nil rather than trapping`() async {
        let artist = Artist(
            name: "T", slug: "t", sourceUrl: nil,
            eras: [era("War", songs: [song("Something Else", key: "something else")])],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let vm = await MainActor.run { ArtistViewModel(artist: artist) }
        let orphan = SongVersion(
            name: "Not In This Tracker", versionTag: nil, badge: nil, featuring: nil,
            producers: nil, collaboration: nil, refs: nil, director: nil,
            creditedArtists: nil, altTitles: nil, notes: nil, ogFilename: nil,
            ogFilenames: nil, samples: nil, trackLength: nil, fileDate: nil,
            leakDate: nil, previewDate: nil, availableLength: nil, quality: nil, streaming: nil,
            links: nil, dateOfRecording: nil, type: nil, sources: nil, rating: nil
        )
        let payload = DescriptionSheet.Payload(
            song: nil, version: orphan,
            artistName: artist.name, artistSlug: artist.slug,
            eraName: "War", eraArt: nil
        )
        let refs = await MainActor.run { vm.crossEraRefs(for: payload) }
        #expect(refs.isEmpty)
        let resolved = await MainActor.run { vm.resolvedSong(for: payload) }
        #expect(resolved == nil)
    }
}
