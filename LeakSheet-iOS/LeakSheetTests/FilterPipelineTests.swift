import Foundation
import SwiftUI
import Testing

@testable import LeakSheet

/// Tests for ArtistViewModel.computeContent — the pure, off-main filter
/// pipeline behind the Best Of / Recent / No Snippets / Misc chips and search.
struct FilterPipelineTests: FilterPipelineFixture {
    // MARK: - Eras branch

    @Test func `empty state keeps every era and song`() {
        let content = compute(FilterState())
        #expect(content.eras.count == 2)
        #expect(content.eras[0].songs.count == 2)
        #expect(content.eras[1].songs.count == 1)
    }

    @Test func `bestOf drops eras without starred versions and non-starred versions`() {
        let content = compute(FilterState(bestOf: true))
        #expect(content.eras.count == 1)
        let eraA = content.eras[0]
        #expect(eraA.era.name == "Era A")
        #expect(eraA.songs.count == 1)
        #expect(eraA.songs[0].baseName == "Starred Song")
        // Only the starred version survives inside the song
        #expect(eraA.songs[0].versions.count == 1)
        #expect(eraA.songs[0].versions[0].badge == "best")
    }

    @Test func `noSnippets drops snippet versions and empty songs`() {
        let content = compute(FilterState(noSnippets: true))
        #expect(content.eras.count == 1)  // Era B had only a snippet
        let eraA = content.eras[0]
        #expect(eraA.songs.count == 2)
        #expect(eraA.songs[0].versions.count == 1)  // V2 snippet dropped
    }

    @Test func `era stats stay unfiltered under filters`() {
        let unfiltered = compute(FilterState())
        let filtered = compute(FilterState(noSnippets: true))
        #expect(filtered.eras[0].stats.total == unfiltered.eras[0].stats.total)
    }

    @Test func `sections are filtered in parallel with songs`() {
        let content = compute(FilterState(bestOf: true))
        #expect(content.eras[0].sections.count == 1)
        #expect(content.eras[0].sections[0].songs.count == 1)
    }

    // MARK: - Search branch

    @Test func `search matches base name and alt titles`() {
        let byName = compute(FilterState(query: "plain"))
        #expect(byName.searchResults.count == 1)
        #expect(byName.searchResults[0].song.baseName == "Plain Song")
        #expect(byName.eras.isEmpty)  // search branch doesn't compute eras

        let byAlt = compute(FilterState(query: "alias one"))
        #expect(byAlt.searchResults.count == 1)
    }

    @Test func `search respects noSnippets`() {
        let all = compute(FilterState(query: "song"))
        let noSnippets = compute(FilterState(query: "song", noSnippets: true))
        #expect(all.searchResults.count > noSnippets.searchResults.count)
        #expect(noSnippets.searchResults.allSatisfy { !($0.version.availableLength ?? "").contains("Snippet") })
    }

    @Test func `exact match ranks above substring match`() {
        let content = compute(FilterState(query: "starred song"))
        #expect(content.searchResults.first?.song.baseName == "Starred Song")
    }

    @Test func `prebuilt search index ranks identically to inline scoring`() {
        // The precomputed haystack must produce byte-identical results to the
        // inline scorer (`compute` uses no index) for every query.
        let idx = ArtistViewModel.Precomputed(artist: artist).searchIndex
        for query in ["song", "plain", "starred song", "alias one", "guest"] {
            let state = FilterState(query: query)
            let indexed = ArtistViewModel.computeContent(
                artist: artist, state: state, eraStats: [:], searchIndex: idx
            ).searchResults
            let inline = compute(state).searchResults
            #expect(indexed.map(\.id) == inline.map(\.id), "ranking diverged for query \(query)")
        }
    }

    // MARK: - Recents branch

    @Test func `recents sort newest first and index streamable playback`() {
        let content = compute(FilterState(recents: true))
        #expect(content.recentResults.count == 4)
        // 04/01 > 03/20 > 02/10 > 01/15
        #expect(content.recentResults[0].version.name == "Snippet Only")
        #expect(content.recentResults[3].version.name == "Starred Song")

        // All fixture versions are streamable → indices align 1:1
        #expect(content.recentPlaybackItems.count == 4)
        for (idx, result) in content.recentResults.enumerated() {
            #expect(content.recentStreamIndex[result.id] == idx)
        }
    }

    @Test func `a preview-only version still reaches recents`() {
        // leak/file date wins when present; a preview-only version has neither
        // and used to be skipped outright, so snippets never showed in Recents.
        let previewOnly = song("Preview Only", versions: [
            version("Preview Only", leakDate: nil, previewDate: "05/01/2024"),
        ])
        let eraC = era("Era C", songs: [previewOnly])
        let withPreview = Artist(
            name: "Test Artist", slug: "test-artist", sourceUrl: nil,
            eras: [eraC], trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let content = ArtistViewModel.computeContent(
            artist: withPreview, state: FilterState(recents: true), eraStats: [:]
        )
        #expect(content.recentResults.count == 1)
        #expect(content.recentResults.first?.version.name == "Preview Only")
    }

    @Test func `recents respect bestOf`() {
        let content = compute(FilterState(bestOf: true, recents: true))
        #expect(content.recentResults.count == 1)
        #expect(content.recentResults[0].version.badge == "best")
    }

    // MARK: - Stats

    @Test func `artist stats sum era stats`() {
        var total = 0
        for era in artist.eras {
            total += ArtistViewModel.computeEraStats(era).total
        }
        #expect(total == 4)
    }

}

// MARK: - Leak-date parsing (2026-07-20 review)

// MARK: - Badge display logic (SPEC §12)
