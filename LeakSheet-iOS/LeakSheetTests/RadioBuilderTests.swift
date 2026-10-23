import Foundation
import Testing

@testable import LeakSheet

/// Seeded so shuffles are reproducible: a failing order can be replayed exactly.
private struct SplitMix64: RandomNumberGenerator {
    var state: UInt64

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
}

private func version(
    _ name: String, tag: String? = nil, quality: String? = nil, leakDate: String? = nil,
    link: String? = "https://pillows.su/f/abc123"
) -> SongVersion {
    SongVersion(
        name: name, versionTag: tag, badge: nil, featuring: nil, producers: nil,
        collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: nil,
        notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil, trackLength: nil,
        fileDate: nil, leakDate: leakDate, previewDate: nil, availableLength: nil,
        quality: quality, streaming: nil, links: link.map { [$0] }, dateOfRecording: nil,
        type: nil, sources: nil, rating: nil
    )
}

private func song(_ baseName: String, _ versions: [SongVersion]) -> Song {
    Song(baseName: baseName, songKey: nil, versions: versions, badge: nil)
}

private func filteredEra(_ name: String, songs: [Song]) -> FilteredEra {
    let era = Era(
        name: name, altNames: nil, description: nil, timeline: nil, artUrl: "art:\(name)",
        sections: [Section(name: "", group: nil, songs: songs)], songCount: nil, versionCount: nil
    )
    return FilteredEra(era: era, sections: era.sections ?? [], songs: songs,
                       stats: ArtistViewModel.computeEraStats(era))
}

private func item(_ name: String, era: String = "E1", slug: String = "ye") -> PlaybackListItem {
    PlaybackListItem(version: version(name), artistName: "Ye", eraName: era, artUrl: "", artistSlug: slug)
}

struct RadioBuilderTests {
    // MARK: - Era radio

    @Test func `era radio picks one best playable version per song and skips unplayable songs`() {
        let alpha = song("Alpha", [
            version("Alpha", tag: "Lossless", quality: "Lossless", link: nil),
            version("Alpha", tag: "Low", quality: "Low Quality"),
        ])
        let beta = song("Beta", [version("Beta", link: nil)])
        let gamma = song("Gamma", [
            version("Gamma", tag: "A", quality: "High Quality"),
            version("Gamma", tag: "B", quality: "CD Quality"),
        ])
        var rng = SplitMix64(state: 1)
        let items = RadioBuilder.eraRadio(
            era: filteredEra("E1", songs: [alpha, beta, gamma]),
            artistName: "Ye", artistSlug: "ye", using: &rng
        )

        #expect(items.count == 2)
        #expect(Set(items.map(\.version.name)) == ["Alpha", "Gamma"])
        #expect(items.first { $0.version.name == "Alpha" }?.version.versionTag == "Low")
        #expect(items.first { $0.version.name == "Gamma" }?.version.versionTag == "B")
        #expect(items.allSatisfy { $0.version.isStreamable && $0.eraName == "E1" && $0.artistSlug == "ye" })
    }

    // MARK: - Credit radio

    @Test func `credit radio only streams streamable versions`() {
        func credited(_ name: String, streamable: Bool) -> CreditProfile.Credited {
            let v = version(name, link: streamable ? "https://pillows.su/f/abc123" : nil)
            return CreditProfile.Credited(
                eraName: "E1", eraArt: nil, song: song(name, [v]), version: v,
                hit: ArtistViewModel.CreditHit(era: 0, section: 0, song: 0, version: 0)
            )
        }
        let credits = [credited("A", streamable: true), credited("B", streamable: false),
                       credited("C", streamable: true), credited("D", streamable: true)]
        var rng = SplitMix64(state: 2)
        let items = RadioBuilder.creditRadio(versions: credits, artistName: "Ye", artistSlug: "ye", using: &rng)

        #expect(items.count == 3)
        #expect(Set(items.map(\.version.name)) == ["A", "C", "D"])
        #expect(items.allSatisfy { !$0.isInserted })
    }

    // MARK: - Newest leaks

    private func artist(_ versions: [SongVersion]) -> Artist {
        let era = Era(
            name: "E1", altNames: nil, description: nil, timeline: nil, artUrl: nil,
            sections: [Section(name: "", group: nil, songs: versions.map { song($0.name, [$0]) })],
            songCount: nil, versionCount: nil
        )
        return Artist(name: "Ye", slug: "ye", sourceUrl: nil, eras: [era], trackerStats: nil,
                      notices: nil, totalSongs: nil, totalVersions: nil, miscEntries: nil, tabs: nil)
    }

    @Test func `newest leaks run newest first and skip unplayable versions`() {
        let items = RadioBuilder.newestLeaks(artist: artist([
            version("Old", leakDate: "01/15/2024"),
            version("Newest", leakDate: "03/20/2024"),
            version("Unplayable", leakDate: "04/01/2024", link: nil),
            version("Middle", leakDate: "02/10/2024"),
        ]))
        #expect(items.map(\.version.name) == ["Newest", "Middle", "Old"])
        #expect(items.allSatisfy { $0.artistSlug == "ye" && $0.eraName == "E1" })
    }

    @Test func `newest leaks are capped`() {
        let many = (0..<(RadioBuilder.newestLeaksCap + 10)).map {
            version("Song \($0)", leakDate: "01/01/2024")
        }
        #expect(RadioBuilder.newestLeaks(artist: artist(many)).count == RadioBuilder.newestLeaksCap)
    }

    // MARK: - Smart shuffle

    @Test func `smart shuffle inserts an unheard suggestion after every third favourite from its era`() {
        let favourites = (0..<7).map { item("F\($0)", era: $0 % 2 == 0 ? "E1" : "E2") }
        let candidates = [
            "ye::E1": [item("C1a"), item("C1b"), item("C1c")],
            "ye::E2": [item("C2a", era: "E2"), item("C2b", era: "E2")],
        ]
        var rng = SplitMix64(state: 3)
        let out = RadioBuilder.smartShuffle(
            favourites: favourites, candidatesByEra: candidates,
            isHeard: { _ in false }, using: &rng
        )

        #expect(out.filter { !$0.isInserted }.count == 7)
        #expect(out.filter(\.isInserted).count == 2)
        var seen = 0
        for (i, entry) in out.enumerated() {
            if entry.isInserted {
                #expect(seen > 0 && seen % 3 == 0)
                #expect(out[i - 1].isInserted == false)
                #expect(out[i - 1].eraName == entry.eraName)
            } else {
                seen += 1
            }
        }
    }

    @Test func `smart shuffle suggests only unheard versions`() {
        let favourites = [item("F0"), item("F1"), item("F2")]
        let candidates = ["ye::E1": [item("heard"), item("fresh")]]
        var rng = SplitMix64(state: 4)
        let out = RadioBuilder.smartShuffle(
            favourites: favourites, candidatesByEra: candidates,
            isHeard: { $0.version.name == "heard" }, using: &rng
        )
        #expect(out.count == 4)
        #expect(out.last?.version.name == "fresh")
        #expect(out.last?.isInserted == true)
    }

    @Test func `smart shuffle skips the suggestion when the era has nothing unheard`() {
        let favourites = [item("F0"), item("F1"), item("F2")]
        let candidates = ["ye::E1": [item("heard")]]
        var rng = SplitMix64(state: 5)
        let out = RadioBuilder.smartShuffle(
            favourites: favourites, candidatesByEra: candidates,
            isHeard: { $0.version.name == "heard" }, using: &rng
        )
        #expect(out.count == 3)
        #expect(out.allSatisfy { !$0.isInserted })
    }

    @Test func `smart shuffle never suggests a favourite it already plays`() {
        let favourites = [item("F0"), item("F1"), item("F2")]
        let candidates = ["ye::E1": [item("F0")]]
        var rng = SplitMix64(state: 6)
        let out = RadioBuilder.smartShuffle(
            favourites: favourites, candidatesByEra: candidates,
            isHeard: { _ in false }, using: &rng
        )
        #expect(out.count == 3)
    }
}
