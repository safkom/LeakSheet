import Foundation
import SwiftUI
import Observation

// MARK: - Filter pipeline value types

/// The complete set of filter inputs. Content is computed off-main for a
/// specific FilterState; views compare against it to know what they render.
nonisolated struct FilterState: Equatable, Sendable {
    var query: String = ""
    var bestOf = false
    var worstOf = false
    var recents = false
    var noSnippets = false
    var misc = false
    /// Selected TabSection id (Released / Best Of / Stems / …). Routes that
    /// tab's entries through the misc pipeline; nil = no tab mode active.
    var tabKey: String? = nil
}

/// One era with its filtered songs/sections and (unfiltered) display stats.
nonisolated struct FilteredEra: Identifiable, Equatable, Sendable {
    let era: Era
    /// Filtered sections — empty when the era has no section structure.
    let sections: [Section]
    /// Filtered flat song list (used when `sections` is empty).
    let songs: [Song]
    /// Unfiltered era totals — cards always show the whole era's numbers.
    let stats: ArtistViewModel.Stats

    var id: String { era.name }

    /// Streamable versions in filtered order — playback context for the era.
    var streamableVersions: [SongVersion] {
        let source = sections.isEmpty ? songs : sections.flatMap(\.songs)
        return source.flatMap(\.versions).filter(\.isStreamable)
    }
}

/// One era's worth of misc/tab entries — prebuilt off-main so the tab
/// page's accordion doesn't regroup ~1900 entries on every render.
nonisolated struct MiscEraGroup: Identifiable, Equatable, Sendable {
    let eraName: String
    let entries: [MiscEntry]
    var id: String { eraName }
}

/// Everything the artist screen renders for one FilterState, computed in a
/// single off-main pass. Only the branch matching the state is populated.
nonisolated struct FilteredContent: Equatable, Sendable {
    let state: FilterState
    let eras: [FilteredEra]
    let searchResults: [ArtistViewModel.SearchResult]
    let recentResults: [ArtistViewModel.RecentResult]
    /// Streamable recents prebuilt as a playback list (tap → play without
    /// mapping the whole result set again).
    let recentPlaybackItems: [PlaybackListItem]
    /// RecentResult.id → index into `recentPlaybackItems`.
    let recentStreamIndex: [String: Int]
    let miscResults: [MiscEntry]
    /// `miscResults` grouped by era in first-appearance order.
    var miscEraGroups: [MiscEraGroup] = []
}

/// One row of the flattened era list. All rows render as direct children of
/// the screen's single LazyVStack so every song row is lazily materialized —
/// nested non-lazy per-era stacks were the chip-toggle freeze.
nonisolated enum EraRow: Identifiable, Equatable, Sendable {
    case card(FilteredEra, expanded: Bool)
    case divider(eraName: String)
    case groupHeader(text: String, eraName: String)
    case sectionHeader(name: String, eraName: String, group: String?)
    case song(Song, eraName: String, eraArt: String?, expanded: Bool, hasMultiple: Bool, isLast: Bool)
    case version(SongVersion, index: Int, song: Song, eraName: String, eraArt: String?, isLast: Bool)
    case eraGap(eraName: String)

    var id: String {
        switch self {
        case .card(let filtered, _): return "card::\(filtered.era.name)"
        case .divider(let era): return "div::\(era)"
        case .groupHeader(let text, let era): return "grp::\(era)::\(text)"
        // Group is part of section identity (Section.id is name+group) —
        // same-named sections under different groups must not collide.
        case .sectionHeader(let name, let era, let group): return "sec::\(era)::\(group ?? "")::\(name)"
        case .song(let song, let era, _, _, _, _): return "song::\(era)::\(song.baseName)"
        case .version(let version, let index, let song, let era, _, _):
            return "ver::\(era)::\(song.baseName)::\(version.id)::\(index)"
        case .eraGap(let era): return "gap::\(era)"
        }
    }
}

/// ViewModel for artist detail screen — search, filter, era state.
///
/// All filtering runs through one pipeline: flag/search changes call
/// `applyFilters()`, which computes a full `FilteredContent` on a detached
/// task and publishes it back on the main actor. Views never filter in body.
@MainActor
@Observable
final class ArtistViewModel {
    // MARK: - Input

    let artist: Artist

    /// Unfiltered tracker totals — the artist is immutable per screen, so
    /// these are computed exactly once.
    let artistStats: Stats
    private let eraStatsByName: [String: Stats]

    // MARK: - Search

    var searchQuery: String = "" {
        didSet { scheduleDebounce() }
    }
    private(set) var debouncedQuery: String = ""
    private var debounceTask: Task<Void, Never>?

    // MARK: - Filters

    var bestOf: Bool = false
    var worstOf: Bool = false
    var recents: Bool = false
    var noSnippets: Bool = false
    /// Misc mode — a strict switch, not a peer filter: when ON, only entries
    /// from the tracker's Misc / Music Videos tabs are shown, never mixed
    /// with era songs; the other chips (and search) filter within them.
    /// Legacy path for payloads without `tabs`; superseded by tab chips.
    var misc: Bool = false
    /// Selected content-tab id (TabSection.id) — same strict-switch
    /// semantics as misc, one chip per parsed tab.
    private(set) var selectedTabKey: String? = nil
    var expandedEra: String? = nil
    /// Expanded multi-version songs, keyed "eraName::baseName". Lives here
    /// (not view @State) because lazy containers discard offscreen state.
    private(set) var expandedSongs: Set<String> = []

    // MARK: - Pipeline output

    private(set) var content: FilteredContent
    /// True while a filter change is being computed off-main. Chips flip
    /// instantly; the list keeps the previous content until the new one lands.
    private(set) var isFiltering = false
    private var filterTask: Task<Void, Never>?

    /// Flattened rows for the eras branch — rebuilt on content/expansion
    /// changes so `body` only iterates.
    private(set) var eraRows: [EraRow] = []

    /// songKey → eras containing that song (only keys spanning >1 era) —
    /// built once in Precomputed.
    private let songKeyEras: [String: [CrossEraRef]]

    // MARK: - Recents windowing

    private(set) var visibleRecents: [RecentResult] = []
    private static let recentsPageSize = 60

    // MARK: - Era display colors

    /// Derived display colors per era, computed once per extracted color.
    private(set) var eraDisplay: [String: EraDisplayColors] = [:]
    /// Colors derived since the last flush — buffered so a burst of cards
    /// finishing extraction in the same runloop turn (cold cache, first
    /// scroll into a section) lands as one `eraDisplay` assignment instead
    /// of one observer invalidation per card, which trips SwiftUI's
    /// "glassEffect() tried to update multiple times per frame" fault.
    private var pendingEraColors: [String: EraDisplayColors] = [:]
    private var eraColorFlushScheduled = false

    var isSearching: Bool { !debouncedQuery.isEmpty }

    var hasMiscEntries: Bool {
        !(artist.miscEntries ?? []).isEmpty
    }

    /// Badge-annotation kinds — never pages (the backend stopped emitting
    /// them 2026-07-18; the filter also hides them in older cached payloads).
    private static let badgeTabKinds: Set<String> = [
        "best_of", "worst_of", "special", "grails", "wanted",
    ]

    /// Parsed content tabs (Misc / Music Videos / Released / Stems / …) —
    /// one switchable chip each. Empty for older cached payloads, which
    /// fall back to the single legacy Misc chip.
    var availableTabs: [TabSection] {
        (artist.tabs ?? []).filter { !Self.badgeTabKinds.contains($0.kind) }
    }

    // MARK: - Init

    /// The heavy startup pass — era stats + the unfiltered content tree —
    /// computed off-main by `make(artist:)` so pushing a huge tracker
    /// doesn't hitch the navigation transition.
    /// One era containing another copy of a song (matched by `songKey`).
    nonisolated struct CrossEraRef: Equatable, Sendable, Identifiable {
        let eraName: String
        let versionCount: Int
        var id: String { eraName }
    }

    nonisolated struct Precomputed: Sendable {
        let eraStatsByName: [String: Stats]
        let artistStats: Stats
        let content: FilteredContent
        /// songKey → every era containing that song, in era order — backs
        /// the description sheet's "Also in" cross-era section.
        let songKeyEras: [String: [CrossEraRef]]

        init(artist: Artist) {
            var statsByName: [String: Stats] = [:]
            var total = 0, available = 0, snippets = 0, confirmed = 0, fullHQ = 0
            var keyEras: [String: [CrossEraRef]] = [:]
            for era in artist.eras {
                let s = ArtistViewModel.computeEraStats(era)
                statsByName[era.name] = s
                total += s.total
                available += s.available
                snippets += s.snippets
                confirmed += s.confirmed
                fullHQ += s.fullHQ
                for song in era.allSongs {
                    guard let key = song.songKey, !key.isEmpty else { continue }
                    // One ref per era per key (a song appears once per era)
                    if keyEras[key]?.last?.eraName != era.name {
                        keyEras[key, default: []].append(
                            CrossEraRef(eraName: era.name, versionCount: song.versions.count)
                        )
                    }
                }
            }
            self.eraStatsByName = statsByName
            self.artistStats = Stats(
                total: total, available: available, snippets: snippets,
                confirmed: confirmed, fullHQ: fullHQ
            )
            self.content = ArtistViewModel.computeContent(
                artist: artist, state: FilterState(), eraStats: statsByName
            )
            // Only keys that actually span content are worth keeping
            self.songKeyEras = keyEras.filter { $0.value.count > 1 }
        }
    }

    /// Other eras containing the same song (by songKey), excluding the one
    /// the user is already looking at. Empty when the song is era-unique.
    func otherEras(forSongKey key: String?, excluding eraName: String) -> [CrossEraRef] {
        guard let key, !key.isEmpty, let refs = songKeyEras[key] else { return [] }
        return refs.filter { $0.eraName != eraName }
    }

    /// Preferred construction path: the stats/content pass runs off-main.
    static func make(artist: Artist) async -> ArtistViewModel {
        let precomputed = await Task.detached(priority: .userInitiated) {
            Precomputed(artist: artist)
        }.value
        return ArtistViewModel(artist: artist, precomputed: precomputed)
    }

    /// Synchronous variant — used by tests and previews; computes the
    /// startup pass inline on the caller's thread.
    convenience init(artist: Artist) {
        self.init(artist: artist, precomputed: Precomputed(artist: artist))
    }

    init(artist: Artist, precomputed: Precomputed) {
        self.artist = artist
        self.eraStatsByName = precomputed.eraStatsByName
        self.artistStats = precomputed.artistStats
        self.content = precomputed.content
        self.songKeyEras = precomputed.songKeyEras

        // Seed era colors from the persisted extraction cache so cards and
        // headers are tinted on first paint without any image download.
        // Keyed by the era's raw art URL (unique per image) rather than era
        // name, which repeats across different artists' eras.
        let cached = EraColorExtractor.cachedColors()
        for era in artist.eras {
            guard let artUrl = era.artUrl, let color = cached[artUrl] else { continue }
            eraDisplay[era.name] = EraDisplayColors.derive(from: color)
        }

        rebuildEraRows()
    }

    // MARK: - Era colors

    /// Idempotent — extraction is deterministic and cached, so the first
    /// derivation per era wins and later callbacks are no-ops. Buffers into
    /// `pendingEraColors` and coalesces same-turn callbacks into a single
    /// `eraDisplay` write on the next runloop tick.
    func setEraColor(eraName: String, dominant: Color) {
        guard eraDisplay[eraName] == nil, pendingEraColors[eraName] == nil else { return }
        pendingEraColors[eraName] = EraDisplayColors.derive(from: dominant)
        scheduleEraColorFlush()
    }

    private func scheduleEraColorFlush() {
        guard !eraColorFlushScheduled else { return }
        eraColorFlushScheduled = true
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.eraColorFlushScheduled = false
            guard !self.pendingEraColors.isEmpty else { return }
            var merged = self.eraDisplay
            for (name, colors) in self.pendingEraColors { merged[name] = colors }
            self.eraDisplay = merged
            self.pendingEraColors.removeAll()
        }
    }

    // MARK: - Debounce

    private func scheduleDebounce() {
        debounceTask?.cancel()
        let q = searchQuery.trimmingCharacters(in: .whitespaces)
        if q.isEmpty {
            debouncedQuery = ""
            applyFilters()
            return
        }
        // Honest indicator: filtering is pending from the moment the query
        // changes, not only after the debounce fires — previously the
        // spinner never appeared during the 200ms window, which is most of
        // a fast query's total latency.
        if q != debouncedQuery {
            isFiltering = true
        }
        debounceTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled else { return }
            self?.debouncedQuery = q
            self?.applyFilters()
        }
    }

    // MARK: - Filter pipeline

    private var currentFilterState: FilterState {
        FilterState(
            query: debouncedQuery.lowercased(),
            bestOf: bestOf,
            worstOf: worstOf,
            recents: recents,
            noSnippets: noSnippets,
            misc: misc,
            tabKey: selectedTabKey
        )
    }

    private func applyFilters() {
        let previousTask = filterTask
        previousTask?.cancel()
        let state = currentFilterState
        guard state != content.state else {
            isFiltering = false
            return
        }
        isFiltering = true
        let artist = self.artist
        let eraStats = self.eraStatsByName
        // Single-flight: wait for the previous detached pass to actually
        // stop before starting the next one. Overlapping passes would race
        // on the shared static DateFormatters in parseDate (DateFormatter
        // isn't safe for concurrent use), and serializing here also means a
        // burst of chip/search changes only ever has one compute in flight
        // instead of piling up wasted work.
        filterTask = Task.detached(priority: .userInitiated) { [weak self] in
            await previousTask?.value
            guard !Task.isCancelled else { return }
            let result = ArtistViewModel.computeContent(artist: artist, state: state, eraStats: eraStats)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                // Stale guard — a newer toggle may have superseded this
                // compute even if cancellation missed it.
                guard self.currentFilterState == state else { return }
                self.content = result
                self.isFiltering = false
                self.resetRecentsWindow()
                self.rebuildEraRows()
            }
        }
    }

    // MARK: - Recents windowing

    private func resetRecentsWindow() {
        visibleRecents = Array(content.recentResults.prefix(Self.recentsPageSize))
    }

    var hasMoreRecents: Bool {
        visibleRecents.count < content.recentResults.count
    }

    func loadMoreRecents() {
        guard hasMoreRecents else { return }
        let next = min(visibleRecents.count + Self.recentsPageSize, content.recentResults.count)
        visibleRecents = Array(content.recentResults.prefix(next))
    }

    /// Playback list + start index for a tapped recents row.
    func recentPlayback(for resultId: String) -> (items: [PlaybackListItem], startAt: Int)? {
        guard let idx = content.recentStreamIndex[resultId] else { return nil }
        return (content.recentPlaybackItems, idx)
    }

    // MARK: - Era expand/collapse

    func toggleEra(_ name: String) {
        if bestOf || worstOf { return }
        expandedEra = expandedEra == name ? nil : name
        rebuildEraRows()
    }

    func isEraExpanded(_ name: String) -> Bool {
        if bestOf || worstOf { return true }
        return expandedEra == name
    }

    func isSongExpanded(eraName: String, baseName: String) -> Bool {
        expandedSongs.contains("\(eraName)::\(baseName)")
    }

    func toggleSongExpansion(eraName: String, baseName: String) {
        let key = "\(eraName)::\(baseName)"
        if expandedSongs.contains(key) {
            expandedSongs.remove(key)
        } else {
            expandedSongs.insert(key)
        }
        rebuildEraRows()
    }

    /// The filtered era backing a row — era-scoped playback context.
    func filteredEra(named name: String) -> FilteredEra? {
        content.eras.first { $0.era.name == name }
    }

    func toggleBestOf() {
        bestOf.toggle()
        if bestOf { worstOf = false }  // contradictory highlight filters
        if !bestOf && !recents { expandedEra = nil }
        // No synchronous rebuildEraRows() here: isEraExpanded treats bestOf
        // as "every era expanded", so rebuilding against the still-stale
        // (unfiltered) `content` would briefly render every song in every
        // era. applyFilters()'s completion rebuilds once `content` actually
        // matches the new bestOf state.
        applyFilters()
    }

    func toggleWorstOf() {
        worstOf.toggle()
        if worstOf { bestOf = false }
        if !worstOf && !recents { expandedEra = nil }
        applyFilters()
    }

    func toggleRecents() {
        recents.toggle()
        if !recents {
            if !bestOf { expandedEra = nil }
            rebuildEraRows()
        }
        applyFilters()
    }

    func toggleNoSnippets() {
        noSnippets.toggle()
        applyFilters()
    }

    func toggleMisc() {
        misc.toggle()
        if misc { selectedTabKey = nil }
        if !misc && !bestOf && !recents {
            expandedEra = nil
            rebuildEraRows()
        }
        applyFilters()
    }

    /// Selects a content tab (tapping the active chip deselects it).
    /// Entering a tab resets the filter chips — except No Snippets, which
    /// keeps excluding short clips on every page.
    func selectTab(_ key: String?) {
        selectedTabKey = (selectedTabKey == key) ? nil : key
        if selectedTabKey != nil {
            misc = false
            bestOf = false
            worstOf = false
            recents = false
        }
        if selectedTabKey == nil && !bestOf && !recents {
            expandedEra = nil
            rebuildEraRows()
        }
        applyFilters()
    }

    // MARK: - Row building (main thread, cheap appends only)

    private func rebuildEraRows() {
        var rows: [EraRow] = []
        rows.reserveCapacity(content.eras.count * 3)
        for filtered in content.eras {
            let eraName = filtered.era.name
            let eraArt = filtered.era.artUrl
            let expanded = isEraExpanded(eraName)
            rows.append(.card(filtered, expanded: expanded))
            if expanded {
                rows.append(.divider(eraName: eraName))
                let startCount = rows.count
                if filtered.sections.isEmpty {
                    appendSongRows(&rows, songs: filtered.songs, eraName: eraName, eraArt: eraArt)
                } else {
                    for section in filtered.sections {
                        if let group = section.group {
                            rows.append(.groupHeader(text: group, eraName: eraName))
                        }
                        if !section.name.isEmpty {
                            rows.append(.sectionHeader(
                                name: section.name, eraName: eraName,
                                group: section.group
                            ))
                        }
                        appendSongRows(&rows, songs: section.songs, eraName: eraName, eraArt: eraArt)
                    }
                }
                // Mark the era's final content row for bottom-corner rounding.
                if rows.count > startCount {
                    rows[rows.count - 1] = markedLast(rows[rows.count - 1])
                }
            }
            rows.append(.eraGap(eraName: eraName))
        }
        eraRows = rows
    }

    private func appendSongRows(_ rows: inout [EraRow], songs: [Song], eraName: String, eraArt: String?) {
        for song in songs {
            let hasMultiple = song.versions.count > 1
            let expanded = hasMultiple && isSongExpanded(eraName: eraName, baseName: song.baseName)
            rows.append(.song(
                song, eraName: eraName, eraArt: eraArt,
                expanded: expanded, hasMultiple: hasMultiple, isLast: false
            ))
            if expanded {
                for (idx, version) in song.versions.enumerated() {
                    rows.append(.version(
                        version, index: idx, song: song,
                        eraName: eraName, eraArt: eraArt, isLast: false
                    ))
                }
            }
        }
    }

    private func markedLast(_ row: EraRow) -> EraRow {
        switch row {
        case .song(let song, let eraName, let eraArt, let expanded, let hasMultiple, _):
            return .song(song, eraName: eraName, eraArt: eraArt,
                         expanded: expanded, hasMultiple: hasMultiple, isLast: true)
        case .version(let version, let index, let song, let eraName, let eraArt, _):
            return .version(version, index: index, song: song,
                            eraName: eraName, eraArt: eraArt, isLast: true)
        default:
            return row
        }
    }

    // MARK: - Content computation (pure, runs off-main)

    nonisolated static func computeContent(
        artist: Artist,
        state: FilterState,
        eraStats: [String: Stats]
    ) -> FilteredContent {
        let empty = FilteredContent(
            state: state, eras: [], searchResults: [], recentResults: [],
            recentPlaybackItems: [], recentStreamIndex: [:], miscResults: []
        )

        if state.misc || state.tabKey != nil {
            let miscResults = computeMiscResults(artist: artist, state: state)
            return FilteredContent(
                state: state, eras: [], searchResults: [], recentResults: [],
                recentPlaybackItems: [], recentStreamIndex: [:],
                miscResults: miscResults,
                miscEraGroups: groupMiscByEra(miscResults)
            )
        }

        if !state.query.isEmpty {
            return FilteredContent(
                state: state, eras: [],
                searchResults: computeSearchResults(artist: artist, state: state),
                recentResults: [], recentPlaybackItems: [], recentStreamIndex: [:],
                miscResults: []
            )
        }

        if state.recents {
            let results = computeRecentResults(artist: artist, state: state)
            var playbackItems: [PlaybackListItem] = []
            var streamIndex: [String: Int] = [:]
            for result in results where result.version.isStreamable {
                streamIndex[result.id] = playbackItems.count
                playbackItems.append(PlaybackListItem(
                    version: result.version,
                    artistName: artist.name,
                    eraName: result.era.name,
                    artUrl: result.era.artUrl ?? "",
                    artistSlug: artist.slug
                ))
            }
            return FilteredContent(
                state: state, eras: [], searchResults: [],
                recentResults: results,
                recentPlaybackItems: playbackItems,
                recentStreamIndex: streamIndex,
                miscResults: []
            )
        }

        // Eras branch
        var eras: [FilteredEra] = []
        eras.reserveCapacity(artist.eras.count)
        for era in artist.eras {
            if Task.isCancelled { return empty }
            let allSongs = era.allSongs
            guard !allSongs.isEmpty else { continue }

            if state.bestOf {
                let hasBest = allSongs.contains { song in
                    song.versions.contains { isBestOfVersion($0) }
                }
                guard hasBest else { continue }
            }
            if state.worstOf {
                let hasWorst = allSongs.contains { song in
                    song.versions.contains { isWorstOfVersion($0) }
                }
                guard hasWorst else { continue }
            }

            let sections = (era.sections ?? []).compactMap { section -> Section? in
                let songs = filterSongs(section.songs, state: state)
                guard !songs.isEmpty else { return nil }
                return Section(name: section.name, group: section.group, songs: songs)
            }
            let songs = filterSongs(allSongs, state: state)
            guard !songs.isEmpty else { continue }

            eras.append(FilteredEra(
                era: era,
                sections: sections,
                songs: songs,
                stats: eraStats[era.name] ?? Stats(total: 0, available: 0, snippets: 0, confirmed: 0, fullHQ: 0)
            ))
        }
        return FilteredContent(
            state: state, eras: eras, searchResults: [], recentResults: [],
            recentPlaybackItems: [], recentStreamIndex: [:], miscResults: []
        )
    }

    private nonisolated static func filterSongs(_ songs: [Song], state: FilterState) -> [Song] {
        guard state.bestOf || state.worstOf || state.noSnippets else { return songs }
        return songs.compactMap { song in
            song.withFilteredVersions { version in
                if state.bestOf && !isBestOfVersion(version) { return false }
                if state.worstOf && !isWorstOfVersion(version) { return false }
                if state.noSnippets && shouldFilterForNoSnippets(version) { return false }
                return true
            }
        }
    }

    // MARK: - Flat search results (ranked)

    nonisolated struct SearchResult: Identifiable, Hashable, Sendable {
        let song: Song
        let version: SongVersion
        let era: Era
        let score: Int

        // Stable id derived from content so SwiftUI's ForEach can diff results
        // across queries instead of rebuilding every row on each keystroke.
        var id: String { "\(era.name)::\(song.baseName)::\(version.id)" }
    }

    private nonisolated static func computeSearchResults(artist: Artist, state: FilterState) -> [SearchResult] {
        let q = state.query
        guard !q.isEmpty else { return [] }
        var results: [SearchResult] = []
        for era in artist.eras {
            if Task.isCancelled { return [] }
            for song in era.allSongs {
                let score = scoreSong(song, query: q)
                guard score > 0 else { continue }
                for version in song.versions {
                    if state.bestOf && !isBestOfVersion(version) { continue }
                    if state.worstOf && !isWorstOfVersion(version) { continue }
                    if state.noSnippets && shouldFilterForNoSnippets(version) { continue }
                    results.append(SearchResult(song: song, version: version, era: era, score: score))
                }
            }
        }
        results.sort { $0.score > $1.score }
        return results
    }

    // MARK: - Recents

    nonisolated struct RecentResult: Identifiable, Equatable, Sendable {
        let song: Song
        let version: SongVersion
        let era: Era
        let timestamp: TimeInterval

        // Stable content-derived id so SwiftUI's ForEach can diff results
        // across filter/query changes instead of rebuilding every row each
        // keystroke (a fresh UUID() on every rebuild caused row flicker
        // and lost expand state).
        var id: String { "\(era.name)::\(song.baseName)::\(version.id)" }
    }

    private nonisolated static func computeRecentResults(artist: Artist, state: FilterState) -> [RecentResult] {
        var results: [RecentResult] = []
        for era in artist.eras {
            if Task.isCancelled { return [] }
            for song in era.allSongs {
                if state.bestOf {
                    let hasBestVersion = song.versions.contains { isBestOfVersion($0) }
                    if !hasBestVersion { continue }
                }
                if state.worstOf {
                    let hasWorstVersion = song.versions.contains { isWorstOfVersion($0) }
                    if !hasWorstVersion { continue }
                }
                for version in song.versions {
                    if state.bestOf && !isBestOfVersion(version) { continue }
                    if state.worstOf && !isWorstOfVersion(version) { continue }
                    if state.noSnippets && shouldFilterForNoSnippets(version) { continue }
                    let dateStr = version.leakDate ?? version.fileDate
                    guard let dateStr, !dateStr.isEmpty else { continue }
                    results.append(RecentResult(
                        song: song, version: version, era: era,
                        timestamp: parseLeakDate(dateStr)
                    ))
                }
            }
        }
        results.sort { $0.timestamp > $1.timestamp }
        return results
    }

    // MARK: - Misc entries

    /// Misc entries after in-mode filters: No Snippets drops unavailable
    /// entries, Recent sorts by date descending, search matches name /
    /// notes / era / type. Best Of restricts to badge-marked names when any
    /// exist (misc entries usually carry no badges — then it's a no-op).
    nonisolated static func groupMiscByEra(_ entries: [MiscEntry]) -> [MiscEraGroup] {
        var order: [String] = []
        var byEra: [String: [MiscEntry]] = [:]
        for entry in entries {
            if byEra[entry.eraName] == nil { order.append(entry.eraName) }
            byEra[entry.eraName, default: []].append(entry)
        }
        return order.map { MiscEraGroup(eraName: $0, entries: byEra[$0] ?? []) }
    }

    private nonisolated static func computeMiscResults(artist: Artist, state: FilterState) -> [MiscEntry] {
        // A selected tab sources that tab's entries; the legacy misc mode
        // reads the flat misc/MV list (older cached payloads have no tabs).
        var entries: [MiscEntry]
        if let tabKey = state.tabKey {
            entries = artist.tabs?.first(where: { $0.id == tabKey })?.entries ?? []
        } else {
            entries = artist.miscEntries ?? []
        }
        if state.noSnippets {
            entries = entries.filter { e in
                let al = (e.available ?? "").lowercased()
                let q = (e.quality ?? "").lowercased()
                return !(al.contains("snippet") || al.contains("unavailable") || q.contains("not available"))
            }
        }
        if state.bestOf {
            let starred = entries.filter { e in
                Badge.allCases.contains { e.name.contains($0.emoji) }
            }
            if !starred.isEmpty { entries = starred }
        }
        if state.worstOf {
            let flagged = entries.filter { $0.name.contains(Badge.worst.emoji) }
            if !flagged.isEmpty { entries = flagged }
        }
        if !state.query.isEmpty {
            let q = state.query
            entries = entries.filter { e in
                e.name.lowercased().contains(q)
                    || (e.notes ?? "").lowercased().contains(q)
                    || e.eraName.lowercased().contains(q)
                    || (e.entryType ?? "").lowercased().contains(q)
            }
        }
        if state.recents {
            entries = entries.sorted {
                Self.parseLeakDate($0.date ?? "") > Self.parseLeakDate($1.date ?? "")
            }
        }
        return entries
    }

    // MARK: - Stats

    nonisolated struct Stats: Equatable, Sendable {
        let total: Int
        let available: Int
        let snippets: Int
        let confirmed: Int
        let fullHQ: Int
    }

    nonisolated static func computeEraStats(_ era: Era) -> Stats {
        var total = 0, available = 0, snippets = 0, confirmed = 0, fullHQ = 0
        for song in era.allSongs {
            for v in song.versions {
                total += 1
                let al = (v.availableLength ?? "").lowercased()
                let q = (v.quality ?? "").lowercased()
                if v.isStreamable { available += 1 }
                if al.contains("snippet") { snippets += 1 }
                if al.contains("confirmed") && !v.isStreamable { confirmed += 1 }
                let isFull = al.contains("full") || al.contains("near full") || al.contains("og file")
                let isHQ = q.contains("hq") || q.contains("high") || q.contains("cd") || q.contains("lossless") || q.contains("og")
                if isFull && isHQ { fullHQ += 1 }
            }
        }
        return Stats(total: total, available: available, snippets: snippets, confirmed: confirmed, fullHQ: fullHQ)
    }

    // MARK: - Private helpers

    // Matches web's BEST_OF_BADGES = new Set(['best', 'special'])
    private nonisolated static let bestOfBadges: Set<Badge> = [.best, .special]

    private nonisolated static func isBestOfVersion(_ v: SongVersion) -> Bool {
        guard let badge = v.badge.flatMap({ Badge(rawValue: $0) }) else { return false }
        return bestOfBadges.contains(badge)
    }

    private nonisolated static func isWorstOfVersion(_ v: SongVersion) -> Bool {
        v.badge.flatMap { Badge(rawValue: $0) } == .worst
    }

    private nonisolated static func scoreSong(_ song: Song, query: String) -> Int {
        let bn = song.baseName.lowercased()
        var alts: [String] = []
        for v in song.versions {
            if let altTitles = v.altTitles {
                alts.append(contentsOf: altTitles.map { $0.lowercased() })
            }
        }
        if bn == query { return 100 }
        if alts.contains(query) { return 90 }
        if bn.hasPrefix(query) { return 70 }
        if alts.contains(where: { $0.hasPrefix(query) }) { return 60 }
        if bn.contains(query) { return 40 }
        for v in song.versions {
            if v.name.lowercased().contains(query) { return 20 }
        }
        if alts.contains(where: { $0.contains(query) }) { return 20 }
        return 0
    }

    private nonisolated static func shouldFilterForNoSnippets(_ v: SongVersion) -> Bool {
        let al = (v.availableLength ?? "").lowercased()
        let q = (v.quality ?? "").lowercased()
        return al.contains("snippet") || al.contains("unavailable") || q.contains("not available")
    }

    // MARK: - Date parsing (cached formatters, safe to call from any thread)

    private nonisolated static let _slashFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MM/dd/yyyy"
        return f
    }()

    private nonisolated static let _isoFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private nonisolated static let _monthYearFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMMM yyyy"
        return f
    }()

    private nonisolated static let _yearFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy"
        return f
    }()

    private nonisolated static func parseLeakDate(_ dateStr: String) -> TimeInterval {
        if let d = _slashFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _isoFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _monthYearFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        // Extract bare year with Swift Regex (compile-time checked)
        if let match = dateStr.firstMatch(of: /(\d{4})/),
           let d = _yearFmt.date(from: String(match.output.1)) {
            return d.timeIntervalSince1970
        }
        return 0
    }
}
