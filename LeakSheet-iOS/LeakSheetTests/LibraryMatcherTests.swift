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
