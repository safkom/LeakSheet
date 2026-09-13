import Foundation
import Testing

@testable import LeakSheet

/// Songs linked by title, alt title and slash-title parts — the description
/// sheet's "Also Known As" row. Linked one hop, never merged.
/// See docs/decisions.md::parser.py::_reconcile_title_misreads.
struct NameLinkTests {
    private func version(_ name: String, alts: [String]? = nil) -> SongVersion {
        SongVersion(
            name: name, versionTag: nil, badge: nil, featuring: nil,
            producers: nil, collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: alts,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
            availableLength: "Full", quality: nil, streaming: nil, links: nil,
            dateOfRecording: nil, type: nil, sources: nil, rating: nil
        )
    }

    private func song(_ name: String, alts: [String]? = nil) -> Song {
        Song(baseName: name, songKey: Song.nameKey(name), versions: [version(name, alts: alts)], badge: nil)
    }

    private func era(_ name: String, _ songs: [Song]) -> Era {
        Era(
            name: name, altNames: nil, description: nil, timeline: nil, artUrl: nil,
            sections: [Section(name: "", group: nil, songs: songs)],
            songCount: nil, versionCount: nil
        )
    }

    private func linked(_ name: String, in artist: Artist, era: String) async -> [String] {
        let vm = await MainActor.run { ArtistViewModel(artist: artist) }
        let s = artist.eras.first { $0.name == era }!.allSongs.first { $0.baseName == name }!
        let payload = SongDetailPayload(
            song: s, version: s.versions[0], artistName: "Ye", artistSlug: "ye", eraName: era, eraArt: nil
        )
        return await MainActor.run { vm.linkedRefs(for: payload).map { "\($0.eraName)/\($0.song.baseName)" } }
    }

    /// Ye's Precious family, as the tracker writes it.
    private var donda: Artist {
        Artist(
            name: "Ye", slug: "ye", sourceUrl: nil,
            eras: [
                era("DONDA [V1]", [
                    song("Precious", alts: ["Hands Down", "Stay On 'Em", "With Child"]),
                    song("Stay On Em / Precious"),
                    song("With Child", alts: ["Precious"]),
                    song("You're Too Precious", alts: ["Precious"]),
                    song("Unrelated"),
                ]),
                era("Donda [V3]", [song("Hands Down")]),
            ],
            trackerStats: nil, notices: nil, totalSongs: nil, totalVersions: nil, miscEntries: nil, tabs: nil
        )
    }

    @Test func `name keys ignore case, diacritics and punctuation`() {
        #expect(Song.nameKey("Stay On 'Em") == Song.nameKey("stay on em"))
        #expect(Song.nameKey("Bitch, Don’t Kill My Vibe") == Song.nameKey("bitch dont kill my vibe"))
        #expect(Song.nameKey("ROSALÍA") == "rosalia")
        #expect(Song.nameKey("???") == "???")
    }

    @Test func `a song links to every song it names and every song naming it`() async {
        let links = await linked("Precious", in: donda, era: "DONDA [V1]")
        #expect(links == [
            "DONDA [V1]/Stay On Em / Precious",
            "DONDA [V1]/With Child",
            "DONDA [V1]/You're Too Precious",
            "Donda [V3]/Hands Down",
        ])
    }

    @Test func `links are one hop, not transitive`() async {
        // "With Child" names Precious, so it reaches every song carrying that
        // name — but not what Precious itself names ("Hands Down") or songs
        // that only name Precious too ("You're Too Precious").
        let links = await linked("With Child", in: donda, era: "DONDA [V1]")
        #expect(links == ["DONDA [V1]/Precious", "DONDA [V1]/Stay On Em / Precious"])
    }

    @Test func `a song with no shared names links to nothing`() async {
        #expect(await linked("Unrelated", in: donda, era: "DONDA [V1]").isEmpty)
    }

    @Test func `search ignores punctuation in titles and alt titles`() {
        var stats: [String: ArtistViewModel.Stats] = [:]
        for era in donda.eras { stats[era.name] = ArtistViewModel.computeEraStats(era) }
        var state = FilterState()
        state.query = "stay on em"
        let content = ArtistViewModel.computeContent(artist: donda, state: state, eraStats: stats)
        let found = Set(content.searchResults.map(\.song.baseName))
        #expect(found.contains("Precious"))
        #expect(found.contains("Stay On Em / Precious"))
    }
}
