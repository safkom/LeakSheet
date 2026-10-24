import Foundation
import Testing

@testable import LeakSheet

struct LibraryMatcherTests {
    private func tracker(_ name: String) -> DiscoveryArtist {
        DiscoveryArtist(name: name, url: "https://x/\(name)", credit: nil, best: nil, upToDate: nil, workingLinks: nil)
    }

    @Test func normalizeFoldsCaseDiacriticsPunctuationAndThe() {
        #expect(LibraryMatcher.normalize("Beyoncé") == "beyonce")
        #expect(LibraryMatcher.normalize("The Weeknd") == "weeknd")
        #expect(LibraryMatcher.normalize("A$AP  Rocky") == "aap rocky")
    }

    @Test func exactNamesOnly() {
        let hits = LibraryMatcher.recommend(
            library: [LibraryArtist(name: "Drake Bell", plays: 50)],
            trackers: [tracker("Drake")]
        )
        #expect(hits.isEmpty)
    }

    @Test func collaborationPartsMatchAndRankByPlays() {
        let hits = LibraryMatcher.recommend(
            library: [
                LibraryArtist(name: "Kanye West", plays: 10),
                LibraryArtist(name: "Travis Scott & Playboi Carti", plays: 99),
            ],
            trackers: [tracker("Kanye West"), tracker("Playboi Carti"), tracker("Nobody")]
        )
        #expect(hits.map(\.name) == ["Playboi Carti", "Kanye West"])
    }

    @Test func emptyLibraryRecommendsNothing() {
        #expect(LibraryMatcher.recommend(library: [], trackers: [tracker("A")]).isEmpty)
    }
}

struct AliasMatchingTests {
    private func tracker(_ name: String) -> DiscoveryArtist {
        DiscoveryArtist(name: name, url: "https://x/\(name)", credit: nil, best: nil, upToDate: nil, workingLinks: nil)
    }

    @Test func aliasMatchesTracker() {
        let library = [LibraryArtist(name: "Kanye West", plays: 40)]
        let hits = LibraryMatcher.recommend(library: library, trackers: [tracker("Ye")], aliases: ["Kanye West": ["Ye"]])
        #expect(hits.map(\.name) == ["Ye"])
    }

    @Test func unmatchedSkipsMatchedAndUnplayed() {
        let library = [
            LibraryArtist(name: "Ye", plays: 5), LibraryArtist(name: "Kanye West", plays: 40),
            LibraryArtist(name: "Never Played", plays: 0),
        ]
        let missing = LibraryMatcher.unmatched(library: library, trackers: [tracker("Ye")], limit: 10)
        #expect(missing.map(\.name) == ["Kanye West"])
    }

    @Test func musicBrainzNeedsConfidentNameOrAliasMatch() {
        let json = #"{"artists":[{"name":"Kanye West","score":100,"aliases":[{"name":"Ye"},{"name":"Kanye"}]}]}"#
        let data = Data(json.utf8)
        #expect(MusicBrainzParsing.aliases(from: data, for: "Kanye West") == ["Ye", "Kanye"])
        #expect(MusicBrainzParsing.aliases(from: data, for: "Ye") == ["Kanye West", "Kanye"])
        #expect(MusicBrainzParsing.aliases(from: data, for: "Someone") == [])
        let weak = Data(#"{"artists":[{"name":"Kanye West","score":60,"aliases":[]}]}"#.utf8)
        #expect(MusicBrainzParsing.aliases(from: weak, for: "Kanye West") == [])
    }
}
