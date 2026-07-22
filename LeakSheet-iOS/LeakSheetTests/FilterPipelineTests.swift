import Foundation
import SwiftUI
import Testing

@testable import LeakSheet

/// Tests for ArtistViewModel.computeContent — the pure, off-main filter
/// pipeline behind the Best Of / Recent / No Snippets / Misc chips and search.
struct FilterPipelineTests {
    // MARK: - Fixture

    private func version(
        _ name: String, tag: String? = nil, badge: String? = nil,
        available: String? = "Full", quality: String? = "High Quality",
        leakDate: String? = nil, link: String? = "https://pillows.su/f/abc123",
        altTitles: [String]? = nil
    ) -> SongVersion {
        SongVersion(
            name: name, versionTag: tag, badge: badge, featuring: nil,
            producers: nil, collaboration: nil, refs: nil, creditedArtists: nil, altTitles: altTitles,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: leakDate,
            availableLength: available, quality: quality,
            links: link.map { [$0] }, qualityColor: nil,
            availableLengthColor: nil, dateOfRecording: nil, type: nil,
            sources: nil, rating: nil
        )
    }

    private func song(_ baseName: String, versions: [SongVersion]) -> Song {
        Song(
            baseName: baseName, songKey: nil, versions: versions, badge: nil,
            availableLength: nil, quality: nil, trackLength: nil,
            leakDate: nil, fileDate: nil
        )
    }

    private func era(_ name: String, songs: [Song]) -> Era {
        Era(
            name: name, altNames: nil, description: nil, timeline: nil,
            statsRaw: nil, stats: nil, artUrl: nil, highlightedProducers: nil,
            sections: [Section(name: "", group: nil, songs: songs)],
            songCount: nil, versionCount: nil
        )
    }

    private var artist: Artist {
        let eraA = era("Era A", songs: [
            song("Starred Song", versions: [
                version("Starred Song", tag: "V1", badge: "best", leakDate: "01/15/2024"),
                version("Starred Song", tag: "V2", available: "Snippet", leakDate: "03/20/2024"),
            ]),
            song("Plain Song", versions: [
                version("Plain Song", leakDate: "02/10/2024", altTitles: ["Alias One"]),
            ]),
        ])
        let eraB = era("Era B", songs: [
            song("Snippet Only", versions: [
                version("Snippet Only", available: "Snippet", leakDate: "04/01/2024"),
            ]),
        ])
        return Artist(
            name: "Test Artist", slug: "test-artist", sourceUrl: nil,
            eras: [eraA, eraB], trackerStats: nil, parseMetadata: nil,
            notices: nil, totalSongs: nil, totalVersions: nil, miscEntries: nil,
            tabs: nil
        )
    }

    private func compute(_ state: FilterState) -> FilteredContent {
        var stats: [String: ArtistViewModel.Stats] = [:]
        for era in artist.eras {
            stats[era.name] = ArtistViewModel.computeEraStats(era)
        }
        return ArtistViewModel.computeContent(artist: artist, state: state, eraStats: stats)
    }

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

    // MARK: - Row rebuild toggles

    @Test @MainActor func `toggleBestOf does not synchronously render unfiltered rows`() {
        let vm = ArtistViewModel(artist: artist)
        vm.toggleBestOf()
        // Right after the call returns — before the detached filter task has
        // had any chance to run — eraRows must still reflect the old,
        // collapsed state. The old bug rebuilt synchronously against the
        // still-unfiltered `content`, and isEraExpanded treats bestOf as
        // "every era expanded", so it briefly rendered every song in every
        // era, unfiltered.
        for row in vm.eraRows {
            if case .card(_, let expanded) = row {
                #expect(expanded == false)
            }
            if case .song = row {
                Issue.record("a song row rendered before bestOf content was refiltered")
            }
        }
    }

    @Test @MainActor func `toggleMisc rebuilds era rows when returning to the base state`() {
        let vm = ArtistViewModel(artist: artist)
        vm.toggleEra("Era A")
        #expect(vm.expandedEra == "Era A")

        vm.toggleMisc()
        vm.toggleMisc()
        // Back to the base filter state — applyFilters() early-returns
        // without ever reaching its own rebuildEraRows() call, so toggleMisc
        // must rebuild synchronously itself once it clears expandedEra.
        // Otherwise eraRows keeps rendering Era A as expanded even though
        // expandedEra is nil, and the next tap on that card is a no-op.
        #expect(vm.expandedEra == nil)
        let eraACard = vm.eraRows.first {
            if case .card(let filtered, _) = $0 { return filtered.era.name == "Era A" }
            return false
        }
        if case .card(_, let expanded) = eraACard {
            #expect(expanded == false)
        } else {
            Issue.record("expected a card row for Era A")
        }
    }

    @Test @MainActor func `same-named placeholder songs get distinct row ids`() {
        // Leak trackers deliberately emit several distinct "???" songs per era
        // (the parser keeps them separate). Their EraRow ids must not collide,
        // or SwiftUI's ForEach silently drops the duplicate rows.
        let mysteryEra = era("Mystery Era", songs: [
            song("???", versions: [version("???", link: nil)]),
            song("???", versions: [version("???", link: nil)]),
            song("???", versions: [version("???", link: nil)]),
        ])
        let a = Artist(
            name: "PH", slug: "ph", sourceUrl: nil, eras: [mysteryEra],
            trackerStats: nil, parseMetadata: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, miscEntries: nil, tabs: nil
        )
        let vm = ArtistViewModel(artist: a)
        vm.toggleEra("Mystery Era")  // expand so the song rows materialize

        let songRowIDs = vm.eraRows.compactMap { row -> String? in
            if case .song = row { return row.id }
            return nil
        }
        #expect(songRowIDs.count == 3)
        #expect(Set(songRowIDs).count == 3)  // all distinct — no id collision
    }

    @Test @MainActor func `setEraColor coalesces same-turn callbacks into one eraDisplay write`() async {
        let vm = ArtistViewModel(artist: artist)
        // Simulate several EraCardViews finishing extraction in the same
        // runloop turn (cold cache, first scroll into a section).
        vm.setEraColor(eraName: "Era A", dominant: Color(red: 0.5, green: 0.1, blue: 0.1))
        vm.setEraColor(eraName: "Era B", dominant: Color(red: 0.1, green: 0.5, blue: 0.1))
        // Neither write has landed yet — both are buffered until the
        // scheduled flush runs on a later tick. If setEraColor wrote
        // eraDisplay directly, this would already contain both keys.
        #expect(vm.eraDisplay.isEmpty)

        // Let the scheduled flush Task run.
        await Task.yield()
        await Task.yield()

        #expect(vm.eraDisplay["Era A"] != nil)
        #expect(vm.eraDisplay["Era B"] != nil)
    }

    // MARK: - Display colors

    @Test @MainActor func `era display colors derive once and are equatable`() {
        let a = EraDisplayColors.derive(from: Color(red: 0.6, green: 0.3, blue: 0.2))
        let b = EraDisplayColors.derive(from: Color(red: 0.6, green: 0.3, blue: 0.2))
        #expect(a == b)
    }

    // MARK: - Image buckets

    // 2026-07-17: 1600 bucket added to match the backend (full-screen art
    // was upscaled from 1280 on ~1290px displays).
    @Test(arguments: [
        (40.0, 3.0, 128), (64.0, 3.0, 320), (96.0, 3.0, 320),
        (160.0, 3.0, 640), (300.0, 3.0, 1280), (430.0, 3.0, 1600),
        (1000.0, 3.0, 1600),
    ])
    func `image size buckets`(points: Double, scale: Double, expected: Int) {
        #expect(ImageCache.bucket(forPointSize: points, scale: scale) == expected)
    }
}

/// Tab-mode routing through the filter pipeline (2026-07-17): a selected
/// TabSection's entries flow into `miscResults` so the existing misc list
/// UI renders every parsed tab.
struct TabModeFilterTests {
    private func entry(_ name: String, era: String = "Era 1", tab: String) -> MiscEntry {
        MiscEntry(
            eraName: era, name: name, notes: nil, entryType: nil, date: nil,
            length: nil, available: nil, quality: nil, streaming: nil,
            links: [], sourceTab: tab
        )
    }

    private func artistWithTabs() -> Artist {
        let released = TabSection(
            kind: "released", name: "📻 Released",
            entries: [entry("Hurricane", tab: "released"), entry("Moon", tab: "released")]
        )
        let stems = TabSection(
            kind: "stems", name: "🌱 Stems",
            entries: [entry("Runaway Stems", tab: "stems")]
        )
        return Artist(
            name: "Test", slug: "test", sourceUrl: nil, eras: [],
            trackerStats: nil, parseMetadata: nil, notices: nil,
            totalSongs: nil, totalVersions: nil,
            miscEntries: [entry("Old Flat Misc", tab: "misc")],
            tabs: [released, stems]
        )
    }

    @Test func `selected tab routes its entries into miscResults`() {
        let artist = artistWithTabs()
        var state = FilterState()
        state.tabKey = artist.tabs![0].id
        let content = ArtistViewModel.computeContent(artist: artist, state: state, eraStats: [:])
        #expect(content.miscResults.map(\.name) == ["Hurricane", "Moon"])
    }

    @Test func `tab entries respect the search query`() {
        let artist = artistWithTabs()
        var state = FilterState()
        state.tabKey = artist.tabs![0].id
        state.query = "moon"
        let content = ArtistViewModel.computeContent(artist: artist, state: state, eraStats: [:])
        #expect(content.miscResults.map(\.name) == ["Moon"])
    }

    @Test func `unknown tab key yields no entries`() {
        let artist = artistWithTabs()
        var state = FilterState()
        state.tabKey = "missing::tab"
        let content = ArtistViewModel.computeContent(artist: artist, state: state, eraStats: [:])
        #expect(content.miscResults.isEmpty)
    }

    @Test func `legacy misc mode still reads the flat list`() {
        let artist = artistWithTabs()
        var state = FilterState()
        state.misc = true
        let content = ArtistViewModel.computeContent(artist: artist, state: state, eraStats: [:])
        #expect(content.miscResults.map(\.name) == ["Old Flat Misc"])
    }
}

/// Worst Of filter (2026-07-18): mirrors Best Of for the 🗑 badge.
struct WorstOfFilterTests {
    private func artist() -> Artist {
        let good = SongVersion(
            name: "Good", versionTag: nil, badge: "best", featuring: nil,
            producers: nil, collaboration: nil, refs: nil, creditedArtists: nil, altTitles: nil,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: nil,
            availableLength: "Full", quality: "High Quality",
            links: ["https://pillows.su/f/a"], qualityColor: nil,
            availableLengthColor: nil, dateOfRecording: nil, type: nil,
            sources: nil, rating: nil
        )
        let bad = SongVersion(
            name: "Bad", versionTag: nil, badge: "worst", featuring: nil,
            producers: nil, collaboration: nil, refs: nil, creditedArtists: nil, altTitles: nil,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: nil,
            availableLength: "Full", quality: "Low Quality",
            links: ["https://pillows.su/f/b"], qualityColor: nil,
            availableLengthColor: nil, dateOfRecording: nil, type: nil,
            sources: nil, rating: nil
        )
        let era = Era(
            name: "Era A", altNames: nil, description: nil, timeline: nil,
            statsRaw: nil, stats: nil, artUrl: nil, highlightedProducers: nil,
            sections: [Section(name: "", group: nil, songs: [
                Song(baseName: "Good", songKey: nil, versions: [good], badge: nil,
                     availableLength: nil, quality: nil, trackLength: nil,
                     leakDate: nil, fileDate: nil),
                Song(baseName: "Bad", songKey: nil, versions: [bad], badge: nil,
                     availableLength: nil, quality: nil, trackLength: nil,
                     leakDate: nil, fileDate: nil),
            ])],
            songCount: nil, versionCount: nil
        )
        return Artist(
            name: "T", slug: "t", sourceUrl: nil, eras: [era],
            trackerStats: nil, parseMetadata: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, miscEntries: nil, tabs: nil
        )
    }

    @Test func `worstOf keeps only worst-badged versions`() {
        var state = FilterState()
        state.worstOf = true
        let content = ArtistViewModel.computeContent(artist: artist(), state: state, eraStats: [:])
        #expect(content.eras.count == 1)
        #expect(content.eras[0].songs.map(\.baseName) == ["Bad"])
    }

    @Test func `badge tab kinds are hidden from available tabs`() async {
        let tabbed = Artist(
            name: "T", slug: "t", sourceUrl: nil, eras: [],
            trackerStats: nil, parseMetadata: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, miscEntries: nil,
            tabs: [
                TabSection(kind: "released", name: "Released", entries: []),
                TabSection(kind: "best_of", name: "Best Of", entries: []),
                TabSection(kind: "grails", name: "Grails", entries: []),
            ]
        )
        let vm = await MainActor.run { ArtistViewModel(artist: tabbed) }
        let kinds = await MainActor.run { vm.availableTabs.map(\.kind) }
        #expect(kinds == ["released"])
    }
}

/// Cross-era song linkage (2026-07-18): Precomputed indexes songKey → eras.
struct CrossEraIndexTests {
    private func song(_ name: String, key: String?, versions: Int = 1) -> Song {
        let v = SongVersion(
            name: name, versionTag: nil, badge: nil, featuring: nil,
            producers: nil, collaboration: nil, refs: nil, creditedArtists: nil, altTitles: nil,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: nil,
            availableLength: "Full", quality: nil, links: nil,
            qualityColor: nil, availableLengthColor: nil,
            dateOfRecording: nil, type: nil, sources: nil, rating: nil
        )
        return Song(
            baseName: name, songKey: key,
            versions: Array(repeating: v, count: versions), badge: nil,
            availableLength: nil, quality: nil, trackLength: nil,
            leakDate: nil, fileDate: nil
        )
    }

    private func era(_ name: String, songs: [Song]) -> Era {
        Era(
            name: name, altNames: nil, description: nil, timeline: nil,
            statsRaw: nil, stats: nil, artUrl: nil, highlightedProducers: nil,
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
            trackerStats: nil, parseMetadata: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, miscEntries: nil, tabs: nil
        )
        let vm = await MainActor.run { ArtistViewModel(artist: artist) }
        let fromWar = await MainActor.run {
            vm.otherEras(forSongKey: "this one here", excluding: "War")
        }
        #expect(fromWar.map(\.eraName) == ["Donda 2"])
        #expect(fromWar.first?.versionCount == 3)
        // Era-unique songs have no cross-era refs
        let unique = await MainActor.run {
            vm.otherEras(forSongKey: "unique", excluding: "War")
        }
        #expect(unique.isEmpty)
    }
}

// MARK: - Leak-date parsing (2026-07-20 review)

@Suite("Leak date parsing")
struct LeakDateParsingTests {
    // "MMM d, yyyy" is the dominant live format (86% of dated versions in
    // the 2026-07-20 TrackerHub sweep, incl. the entire Ye tracker); before
    // the fix it fell through to the bare-year regex and lost day precision.
    @Test func abbreviatedMonthDayParsesToFullPrecision() {
        let a = ArtistViewModel.parseLeakDate("Mar 20, 2023")
        let b = ArtistViewModel.parseLeakDate("Mar 21, 2023")
        #expect(a > 0)
        #expect(b - a == 86_400)  // day precision, not year-bucketed
    }

    @Test func fullMonthDayParses() {
        #expect(ArtistViewModel.parseLeakDate("March 20, 2023") ==
                ArtistViewModel.parseLeakDate("Mar 20, 2023"))
    }

    @Test func abbreviatedMonthYearParses() {
        let v = ArtistViewModel.parseLeakDate("Mar 2023")
        #expect(v == ArtistViewModel.parseLeakDate("March 2023"))
        #expect(v > 0)
    }

    @Test func existingFormatsStillParse() {
        #expect(ArtistViewModel.parseLeakDate("03/20/2023") > 0)
        #expect(ArtistViewModel.parseLeakDate("2023-03-20") > 0)
        #expect(ArtistViewModel.parseLeakDate("March 2023") > 0)
        #expect(ArtistViewModel.parseLeakDate("2023") > 0)
    }

    @Test func yearFallbackAndGarbage() {
        // Unknown format containing a year still year-buckets…
        #expect(ArtistViewModel.parseLeakDate("sometime in 2019?") > 0)
        // …and true garbage sorts to the bottom.
        #expect(ArtistViewModel.parseLeakDate("n/a") == 0)
        #expect(ArtistViewModel.parseLeakDate("") == 0)
    }
}
