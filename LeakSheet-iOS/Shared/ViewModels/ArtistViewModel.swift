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
    /// Combined "grails" filter — matches the grail AND wanted badges (the
    /// most sought-after tracks), surfaced as a single chip.
    var grails = false
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
    // `ordinal` disambiguates same-baseName songs — see DECISIONS.md::ArtistViewModel.swift::song-ordinal
    case song(Song, eraName: String, eraArt: String?, expanded: Bool, hasMultiple: Bool, isLast: Bool, ordinal: Int)
    case version(SongVersion, index: Int, song: Song, eraName: String, eraArt: String?, isLast: Bool, songOrdinal: Int)
    case eraGap(eraName: String)

    var id: String {
        switch self {
        case .card(let filtered, _): return "card::\(filtered.era.name)"
        case .divider(let era): return "div::\(era)"
        case .groupHeader(let text, let era): return "grp::\(era)::\(text)"
        // Group is part of section identity (Section.id is name+group) —
        // same-named sections under different groups must not collide.
        case .sectionHeader(let name, let era, let group): return "sec::\(era)::\(group ?? "")::\(name)"
        case .song(let song, let era, _, _, _, _, let ord): return "song::\(era)::\(ord)::\(song.baseName)"
        case .version(let version, let index, let song, let era, _, _, let songOrd):
            return "ver::\(era)::\(songOrd)::\(song.baseName)::\(version.id)::\(index)"
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
    /// Combined "grails" filter — grail + wanted badges, one chip.
    var grails: Bool = false
    var recents: Bool = false
    var noSnippets: Bool = false

    /// The badge "highlight" filters — each expands every matching era and
    /// they are mutually exclusive (only one active at a time), so the AND
    /// logic in the filter pipeline never intersects two badge sets.
    var isBadgeFilterActive: Bool { bestOf || worstOf || grails }
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
    /// baseName → every era containing it (see Precomputed.baseNameEras).
    private let baseNameEras: [String: [CrossEraRef]]

    /// Prebuilt lowercased search haystack (see Precomputed.searchIndex).
    private let searchIndex: [[SongSearchFields]]

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
        let eraArt: String?
        let song: Song
        var id: String { eraName }
    }

    /// One playable version of a cross-era song, with the era it belongs to —
    /// what the description sheet's version picker lists and switches between.
    nonisolated struct CrossEraVersion: Identifiable, Sendable {
        let version: SongVersion
        let song: Song?
        let eraName: String
        let eraArt: String?
        var id: String { "\(eraName)::\(version.id)" }
    }

    nonisolated struct Precomputed: Sendable {
        let eraStatsByName: [String: Stats]
        let artistStats: Stats
        let content: FilteredContent
        /// songKey → every era containing that song, in era order — backs
        /// the description sheet's "Also in" cross-era section.
        let songKeyEras: [String: [CrossEraRef]]
        /// baseName → every era containing it. The songKey-less fallback for
        /// both `resolvedSong` and `crossEraRefs`, so neither has to rescan
        /// the tracker (Era.allSongs rebuilds its array on each access).
        let baseNameEras: [String: [CrossEraRef]]
        /// Per-era, per-song lowercased search haystack, built once off-main so
        /// each keystroke's scoring is comparison-only (no re-lowercasing every
        /// song name / alt title / version name across the whole tracker).
        /// Shape mirrors `artist.eras[i].allSongs[j]`.
        let searchIndex: [[SongSearchFields]]

        init(artist: Artist) {
            var statsByName: [String: Stats] = [:]
            var total = 0, available = 0, snippets = 0, confirmed = 0, fullHQ = 0
            var keyEras: [String: [CrossEraRef]] = [:]
            var byBaseName: [String: [CrossEraRef]] = [:]
            for era in artist.eras {
                let s = ArtistViewModel.computeEraStats(era)
                statsByName[era.name] = s
                total += s.total
                available += s.available
                snippets += s.snippets
                confirmed += s.confirmed
                fullHQ += s.fullHQ
                for song in era.allSongs {
                    byBaseName[song.baseName, default: []].append(
                        CrossEraRef(eraName: era.name, eraArt: era.artUrl, song: song)
                    )
                    guard let key = song.songKey, !key.isEmpty else { continue }
                    // One ref per era per key (a song appears once per era)
                    if keyEras[key]?.last?.eraName != era.name {
                        keyEras[key, default: []].append(
                            CrossEraRef(eraName: era.name, eraArt: era.artUrl, song: song)
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
            self.baseNameEras = byBaseName
            self.searchIndex = artist.eras.map { $0.allSongs.map(SongSearchFields.init(song:)) }
        }
    }

    /// Resolve the full, unfiltered song for a description payload — the row
    /// that opened the sheet may be a single-version snapshot from the
    /// current filter.
    func resolvedSong(for payload: SongDetailPayload) -> Song? {
        let refs = crossEraRefs(for: payload)
        return refs.first(where: { $0.eraName == payload.eraName })?.song
            ?? refs.first?.song
            ?? payload.song
    }

    /// Every era containing this payload's song. Prefers `songKey`, which only
    /// indexes songs spanning >1 era, and falls back to the base-name index —
    /// which also covers era-unique songs and payloads carrying no songKey.
    ///
    /// A nil `payload.song` is NOT a dead end: Now Playing and Favourites only
    /// hold a bare `SongVersion`, and bailing here is why the description sheet
    /// opened from the player's Info button lost its Versions picker, its alt
    /// title, and its song-level credits. The version's own `derivedBaseName`
    /// (tag stripped) is the same key the base-name index is built on.
    func crossEraRefs(for payload: SongDetailPayload) -> [CrossEraRef] {
        if let payloadSong = payload.song {
            if let key = payloadSong.songKey, !key.isEmpty, let refs = songKeyEras[key] {
                return refs
            }
            return baseNameEras[payloadSong.baseName] ?? []
        }
        return baseNameEras[payload.version.derivedBaseName] ?? []
    }

    /// How many era covers are warmed before the artist screen is pushed.
    /// Roughly two screenfuls of collapsed cards — enough that the first thing
    /// the user sees is never a grid of placeholders, without making a 40-era
    /// tracker wait on 40 downloads before it opens.
    static let coldStartArtCount = 8

    /// Preferred construction path: the stats/content pass runs off-main.
    ///
    /// `warmArt` pulls the first few era covers (and their dominant colours)
    /// into the cache before returning. The caller is still showing the landing
    /// spinner at this point, so the work is free; without it the screen
    /// rendered, *then* started fetching, and the first pass down a cold
    /// tracker was a sequence of grey cards popping into colour.
    static func make(artist: Artist, warmArt: Bool = true) async -> ArtistViewModel {
        let precomputed = await Task.detached(priority: .userInitiated) {
            Precomputed(artist: artist)
        }.value
        let vm = ArtistViewModel(artist: artist, precomputed: precomputed)
        if warmArt {
            await vm.warmEraArt(limit: coldStartArtCount)
        }
        return vm
    }

    /// Load era covers into the image cache and derive their display colours.
    ///
    /// `ImageCache.prefetch` alone is not enough: it warms bytes but never
    /// extracts colour, so cards still arrived grey and re-tinted a frame
    /// later. Extraction is cheap once the image is decoded and cached.
    ///
    /// `limit` nil warms every era (the background pass from ArtistView).
    func warmEraArt(limit: Int? = nil) async {
        let eras = limit.map { Array(artist.eras.prefix($0)) } ?? artist.eras
        let targets: [(artUrl: String, url: URL)] = eras.compactMap { era in
            guard let art = era.artUrl,
                  eraDisplay[era.name] == nil,
                  let url = APIClient.shared.imageProxyURL(for: art, width: 320)
            else { return nil }
            return (art, url)
        }
        guard !targets.isEmpty else { return }

        await withTaskGroup(of: (String, Color)?.self) { group in
            // Same ceiling as ImageCache.prefetch — enough to saturate the
            // link without starving the cover the user is looking at.
            let slots = 4
            var next = 0
            var inFlight = 0
            func addTask() {
                let target = targets[next]
                next += 1
                inFlight += 1
                group.addTask {
                    guard let image = await ImageCache.shared.loadImage(
                        from: target.url, maxPixelSize: 320
                    ) else { return nil }
                    guard let color = await EraColorExtractor.shared.extractColor(
                        fromImage: image, cacheKey: target.artUrl
                    ) else { return nil }
                    return (target.artUrl, color)
                }
            }
            while next < targets.count && inFlight < slots { addTask() }
            while inFlight > 0 {
                let result = await group.next() ?? nil
                inFlight -= 1
                if let (artUrl, color) = result {
                    for era in eras where era.artUrl == artUrl {
                        setEraColor(eraName: era.name, dominant: color)
                    }
                }
                if Task.isCancelled { break }
                if next < targets.count { addTask() }
            }
            group.cancelAll()
        }
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
        self.baseNameEras = precomputed.baseNameEras
        self.searchIndex = precomputed.searchIndex

        // Seed era colors from persisted cache — see DECISIONS.md::EraColorExtractor.swift::cache-key
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
        // Honest filtering indicator — see DECISIONS.md::ArtistViewModel.swift::filtering-indicator
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
            grails: grails,
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
        let searchIndex = self.searchIndex
        // Single-flight filtering — see DECISIONS.md::ArtistViewModel.swift::single-flight-filter
        filterTask = Task.detached(priority: .userInitiated) { [weak self] in
            await previousTask?.value
            guard !Task.isCancelled else { return }
            let result = ArtistViewModel.computeContent(artist: artist, state: state, eraStats: eraStats, searchIndex: searchIndex)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                // Stale guard — a newer toggle may have superseded this
                // compute even if cancellation missed it.
                guard self.currentFilterState == state else { return }
                self.content = result
                self.isFiltering = false
                // Ordinals are positions within the FILTERED era, so a filter
                // change renumbers them. Keeping the set meant expanding the
                // 4th song, toggling a chip, and finding a different song
                // expanded instead.
                self.expandedSongs.removeAll()
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
        if isBadgeFilterActive { return }
        expandedEra = expandedEra == name ? nil : name
        rebuildEraRows()
    }

    func isEraExpanded(_ name: String) -> Bool {
        if isBadgeFilterActive { return true }
        return expandedEra == name
    }

    func isSongExpanded(eraName: String, ordinal: Int) -> Bool {
        expandedSongs.contains("\(eraName)::\(ordinal)")
    }

    func toggleSongExpansion(eraName: String, ordinal: Int) {
        // Keyed by positional ordinal, not baseName, so expanding one of
        // several same-named ("???") songs doesn't expand its siblings.
        let key = "\(eraName)::\(ordinal)"
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
        // The badge filters are mutually exclusive — enabling one clears the
        // others so the AND pipeline never intersects two badge sets.
        if bestOf { worstOf = false; grails = false }
        if !isBadgeFilterActive && !recents { expandedEra = nil }
        // No sync rebuildEraRows() here — see DECISIONS.md::ArtistViewModel.swift::no-sync-rebuild
        applyFilters()
    }

    func toggleWorstOf() {
        worstOf.toggle()
        if worstOf { bestOf = false; grails = false }
        if !isBadgeFilterActive && !recents { expandedEra = nil }
        applyFilters()
    }

    func toggleGrails() {
        grails.toggle()
        if grails { bestOf = false; worstOf = false }
        if !isBadgeFilterActive && !recents { expandedEra = nil }
        applyFilters()
    }

    func toggleRecents() {
        recents.toggle()
        if !recents {
            if !isBadgeFilterActive { expandedEra = nil }
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
        if !misc && !isBadgeFilterActive && !recents {
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
            grails = false
            recents = false
        }
        if selectedTabKey == nil && !isBadgeFilterActive && !recents {
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
                // One running ordinal across all sections of the era so every
                // song row has a unique positional identity within the era.
                var ordinal = 0
                if filtered.sections.isEmpty {
                    appendSongRows(&rows, songs: filtered.songs, eraName: eraName, eraArt: eraArt, ordinal: &ordinal)
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
                        appendSongRows(&rows, songs: section.songs, eraName: eraName, eraArt: eraArt, ordinal: &ordinal)
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

    private func appendSongRows(_ rows: inout [EraRow], songs: [Song], eraName: String, eraArt: String?, ordinal: inout Int) {
        for song in songs {
            let hasMultiple = song.hasMultipleVersions
            let expanded = hasMultiple && isSongExpanded(eraName: eraName, ordinal: ordinal)
            rows.append(.song(
                song, eraName: eraName, eraArt: eraArt,
                expanded: expanded, hasMultiple: hasMultiple, isLast: false, ordinal: ordinal
            ))
            if expanded {
                // `versions`, i.e. what matched the filter — the same array
                // the row's count and chevron are derived from. Expanding
                // `allVersions` here put versions the badge filter had
                // excluded back on screen while the row still claimed the
                // filtered count. Playback context is built from
                // `allVersions` elsewhere, so auto-advance is unaffected.
                for (idx, version) in song.versions.enumerated() {
                    rows.append(.version(
                        version, index: idx, song: song,
                        eraName: eraName, eraArt: eraArt, isLast: false, songOrdinal: ordinal
                    ))
                }
            }
            ordinal += 1
        }
    }

    private func markedLast(_ row: EraRow) -> EraRow {
        switch row {
        case .song(let song, let eraName, let eraArt, let expanded, let hasMultiple, _, let ordinal):
            return .song(song, eraName: eraName, eraArt: eraArt,
                         expanded: expanded, hasMultiple: hasMultiple, isLast: true, ordinal: ordinal)
        case .version(let version, let index, let song, let eraName, let eraArt, _, let songOrdinal):
            return .version(version, index: index, song: song,
                            eraName: eraName, eraArt: eraArt, isLast: true, songOrdinal: songOrdinal)
        default:
            return row
        }
    }
}
