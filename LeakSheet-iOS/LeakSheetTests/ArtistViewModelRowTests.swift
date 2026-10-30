import Foundation
import SwiftUI
import Testing

@testable import LeakSheet

/// The view model's row rebuilds and era colours, on the filter-pipeline fixture.
struct ArtistViewModelRowTests: FilterPipelineFixture {
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

    @Test @MainActor func `leaving a tab rebuilds era rows when returning to the base state`() {
        let vm = ArtistViewModel(artist: artist)
        vm.toggleEra("Era A")
        #expect(vm.expandedEra == "Era A")

        vm.selectTab("misc::Misc")
        vm.selectTab("misc::Misc")
        // Back to the base filter state — applyFilters() early-returns
        // without ever reaching its own rebuildEraRows() call, so selectTab
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
            trackerStats: nil, notices: nil,
            totalSongs: nil, totalVersions: nil, tabs: nil
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

    @Test @MainActor func `every era row id is unique, with one header per group run`() {
        let mystery = { song("???", versions: [version("???", link: nil)]) }
        let sections = [
            Section(name: "Surfaced", group: "Deluxe", songs: [mystery()]),
            Section(name: "Unsurfaced", group: "Deluxe", songs: [mystery()]),
            Section(name: "Surfaced", group: "Other", songs: [mystery()]),
            Section(name: "Surfaced", group: "Deluxe", songs: [mystery(), mystery()]),
        ]
        let grouped = Era(
            name: "Grouped Era", altNames: nil, description: nil, timeline: nil, artUrl: nil,
            sections: sections, songCount: nil, versionCount: nil
        )
        let a = Artist(
            name: "G", slug: "g", sourceUrl: nil, eras: [grouped, era("Next Era", songs: [mystery()])],
            trackerStats: nil, notices: nil, totalSongs: nil, totalVersions: nil, tabs: nil
        )
        let vm = ArtistViewModel(artist: a)
        vm.toggleEra("Grouped Era")

        let ids = vm.eraRows.map(\.id)
        #expect(Set(ids).count == ids.count)
        let groupHeaders = vm.eraRows.compactMap { row -> String? in
            if case .groupHeader(let text, _, _) = row { return text }
            return nil
        }
        #expect(groupHeaders == ["Deluxe", "Other", "Deluxe"])
    }

    @Test @MainActor func `a filter that hides the playing era keeps it registered, empty`() async throws {
        let vm = ArtistViewModel(artist: artist)
        let revision = vm.eraPlaybackRevision
        vm.toggleBestOf()  // Era B has no starred song
        for _ in 0..<300 where vm.eraPlaybackRevision == revision {
            try await Task.sleep(for: .milliseconds(10))
        }
        #expect(vm.eraPlaybackContexts.map(\.eraName) == ["Era A", "Era B"])
        #expect(vm.eraPlaybackContexts.last?.versions.isEmpty == true)
    }

    @Test func `search, recents and tabs roll over through the whole tracker`() {
        for state in [FilterState(query: "song"), FilterState(recents: true), FilterState()] {
            let result = compute(state)
            #expect(ArtistViewModel.filteredEraContexts(artist: artist, state: state, result: result) == nil)
        }
    }

    @Test @MainActor func `era rollover follows the active filters`() async throws {
        let vm = ArtistViewModel(artist: artist)
        let isSnippet = { (v: SongVersion) in v.availableLength == "Snippet" }
        #expect(vm.eraPlaybackContexts.flatMap(\.versions).contains(where: isSnippet))

        let revision = vm.eraPlaybackRevision
        vm.toggleNoSnippets()
        for _ in 0..<300 where vm.eraPlaybackRevision == revision {
            try await Task.sleep(for: .milliseconds(10))
        }
        #expect(vm.eraPlaybackRevision != revision)
        #expect(!vm.eraPlaybackContexts.flatMap(\.versions).contains(where: isSnippet))
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
}
