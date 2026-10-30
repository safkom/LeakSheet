import Foundation
import SwiftUI
import Testing

@testable import LeakSheet

/// Tab-mode routing through the filter pipeline (2026-07-17): a selected
/// TabSection's entries flow into `miscResults` so the existing misc list
/// UI renders every parsed tab.
struct TabModeFilterTests {
    private func entry(_ name: String, era: String = "Era 1", tab: String, row: Int = 0) -> MiscEntry {
        MiscEntry(
            eraName: era, rowIndex: row, name: name, notes: nil, entryType: nil, date: nil,
            length: nil, available: nil, quality: nil, streaming: nil,
            links: [], sourceTab: tab
        )
    }

    private func artistWithTabs() -> Artist {
        let released = TabSection(
            kind: "released", name: "📻 Released",
            entries: [entry("Hurricane", tab: "released", row: 0), entry("Moon", tab: "released", row: 1)]
        )
        let stems = TabSection(
            kind: "stems", name: "🌱 Stems",
            entries: [entry("Runaway Stems", tab: "stems")]
        )
        return Artist(
            name: "Test", slug: "test", sourceUrl: nil, eras: [],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil,
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
}

/// Worst Of filter (2026-07-18): mirrors Best Of for the 🗑 badge.
struct WorstOfFilterTests {
    private func artist() -> Artist {
        let good = SongVersion(
            name: "Good", versionTag: nil, badge: "best", featuring: nil,
            producers: nil, collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: nil,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
            availableLength: "Full", quality: "High Quality", streaming: nil,
            links: ["https://pillows.su/f/a"], dateOfRecording: nil, type: nil,
            sources: nil, rating: nil
        )
        let bad = SongVersion(
            name: "Bad", versionTag: nil, badge: "worst", featuring: nil,
            producers: nil, collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: nil,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
            availableLength: "Full", quality: "Low Quality", streaming: nil,
            links: ["https://pillows.su/f/b"], dateOfRecording: nil, type: nil,
            sources: nil, rating: nil
        )
        let era = Era(
            name: "Era A", altNames: nil, description: nil, timeline: nil,
            artUrl: nil,
            sections: [Section(name: "", group: nil, songs: [
                Song(baseName: "Good", songKey: nil, versions: [good], badge: nil),
                Song(baseName: "Bad", songKey: nil, versions: [bad], badge: nil),
            ])],
            songCount: nil, versionCount: nil
        )
        return Artist(
            name: "T", slug: "t", sourceUrl: nil, eras: [era],
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
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
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil,
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

/// Best Of, Worst Of and Grails on a tab: a filter with no matching entry shows an
/// empty tab, never the unfiltered list.
struct TabBadgeFilterTests {
    private func names(_ entries: [String], _ configure: (inout FilterState) -> Void) -> [String] {
        let tab = TabSection(
            kind: "released", name: "📻 Released",
            entries: entries.enumerated().map { offset, name in
                MiscEntry(
                    eraName: "Era 1", rowIndex: offset, name: name, notes: nil, entryType: nil, date: nil,
                    length: nil, available: nil, quality: nil, streaming: nil,
                    links: [], sourceTab: "released"
                )
            }
        )
        let artist = Artist(
            name: "Test", slug: "test", sourceUrl: nil, eras: [],
            trackerStats: nil, notices: nil, totalSongs: nil, totalVersions: nil,
            tabs: [tab]
        )
        var state = FilterState()
        state.tabKey = tab.id
        configure(&state)
        return ArtistViewModel.computeContent(artist: artist, state: state, eraStats: [:]).miscResults.map(\.name)
    }

    @Test func `bestOf with no starred entry is empty`() {
        #expect(names(["Hurricane", "Moon"]) { $0.bestOf = true }.isEmpty)
    }

    @Test func `bestOf keeps only starred entries`() {
        let result = names(["Hurricane \(Badge.best.emoji)", "Moon"]) { $0.bestOf = true }
        #expect(result == ["Hurricane \(Badge.best.emoji)"])
    }

    @Test func `worstOf with no flagged entry is empty`() {
        #expect(names(["Hurricane", "Moon"]) { $0.worstOf = true }.isEmpty)
    }

    @Test func `grails with no sought entry is empty`() {
        #expect(names(["Hurricane", "Moon"]) { $0.grails = true }.isEmpty)
    }
}
