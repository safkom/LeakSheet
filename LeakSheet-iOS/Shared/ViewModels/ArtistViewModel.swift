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

    /// Filtered songs in display order, whether or not the era is sectioned.
    var allSongs: [Song] {
        sections.isEmpty ? songs : sections.flatMap(\.songs)
    }

    /// Streamable versions in filtered order — playback context for the era.
    var streamableVersions: [SongVersion] {
        allSongs.flatMap(\.versions).filter(\.isStreamable)
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

/// One row of the flattened era list. All rows are direct children of the screen's
/// single LazyVStack, so every song row materializes lazily.
nonisolated enum EraRow: Identifiable, Equatable, Sendable {
    case card(FilteredEra, expanded: Bool)
    case divider(eraName: String)
    case groupHeader(text: String, eraName: String)
    case sectionHeader(name: String, eraName: String, group: String?, notes: String? = nil)
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
        case .sectionHeader(let name, let era, let group, _): return "sec::\(era)::\(group ?? "")::\(name)"
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
    private let tabStatsByKey: [String: Stats]

    /// Totals for the list currently on screen (song tree or content tab); the
    /// stats bar and the nav subtitle both read this.
    var visibleStats: Stats {
        guard let key = selectedTabKey, let stats = tabStatsByKey[key] else {
            return artistStats
        }
        return stats
    }

    /// Whether the visible list is entries from a content tab rather than the
    /// song tree — the two are counted in different units.
    var isShowingTabEntries: Bool {
        selectedTabKey != nil && tabStatsByKey[selectedTabKey ?? ""] != nil
    }

    // MARK: - Search

    /// Set when the shown data is a saved copy or a refresh failed; the
    /// artist screen shows it in place of the data age.
    var loadNotice: String?

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

    /// The badge "highlight" filters: each expands every matching era, and only one
    /// is active at a time, so the AND pipeline never intersects two badge sets.
    var isBadgeFilterActive: Bool { bestOf || worstOf || grails }
    /// Misc mode — a strict switch, not a peer filter: only Misc / Music Videos entries
    /// show, filtered by the other chips and search. Legacy path for payloads without `tabs`.
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

    /// The appearance the cached `eraDisplay` values were derived for; switching
    /// re-derives them (the dominant colours are appearance-independent).
    private(set) var colorScheme: ColorScheme = .dark

    /// songKey → eras containing that song (only keys spanning >1 era) —
    /// built once in Precomputed.
    private let songKeyEras: [String: [CrossEraRef]]
    /// baseName → every era containing it (see Precomputed.baseNameEras).
    private let baseNameEras: [String: [CrossEraRef]]
    /// Name key → songs carrying it as a title / as an alt title (see
    /// Precomputed.titleKeySongs), and each era's position for ordering.
    private let titleKeySongs: [String: [CrossEraRef]]
    private let altTitleKeySongs: [String: [CrossEraRef]]
    private let eraOrder: [String: Int]

    /// Prebuilt lowercased search haystack (see Precomputed.searchIndex).
    private let searchIndex: [[SongSearchFields]]
    /// Ordered era playback contexts (see Precomputed.eraPlaybackContexts).
    let eraPlaybackContexts: [EraSongContext]

    // MARK: - Recents windowing

    private(set) var visibleRecents: [RecentResult] = []
    private static let recentsPageSize = 60

    // MARK: - Era display colors

    /// Derived display colors per era, computed once per extracted color.
    private(set) var eraDisplay: [String: EraDisplayColors] = [:]
    /// Colors derived since the last flush, so a burst of extractions lands as one
    /// `eraDisplay` write (per-card writes trip the glassEffect multiple-updates fault).
    private var pendingEraColors: [String: EraDisplayColors] = [:]
    private var eraColorFlushScheduled = false

    var isSearching: Bool { !debouncedQuery.isEmpty }

    var hasMiscEntries: Bool {
        !(artist.miscEntries ?? []).isEmpty
    }

    /// Badge-annotation kinds: never pages. Older cached payloads may still carry them.
    private static let badgeTabKinds: Set<String> = [
        "best_of", "worst_of", "special", "grails", "wanted",
    ]

    /// Parsed content tabs (Misc / Music Videos / Released / Stems / …) —
    /// one switchable chip each. Empty for older cached payloads, which
    /// fall back to the single legacy Misc chip.
    var availableTabs: [TabSection] {
        (artist.tabs ?? []).filter { !Self.badgeTabKinds.contains($0.kind) }
    }

    /// Display name of the selected content tab, for anything that has to name
    /// the page — nil on the song tree, or on the legacy flat Misc mode.
    var selectedTabName: String? {
        guard let key = selectedTabKey else { return nil }
        return availableTabs.first { $0.id == key }?.name
    }

    // MARK: - Init

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

    /// The heavy startup pass (era stats + the unfiltered content tree), computed
    /// off-main by `make(artist:)` so pushing a huge tracker doesn't hitch navigation.
    nonisolated struct Precomputed: Sendable {
        let eraStatsByName: [String: Stats]
        let artistStats: Stats
        /// TabSection.id → that tab's own totals, so the stats bar can describe
        /// whatever list is actually on screen.
        let tabStatsByKey: [String: Stats]
        let content: FilteredContent
        /// songKey → every era containing that song, in era order — backs
        /// the description sheet's "Also in" cross-era section.
        let songKeyEras: [String: [CrossEraRef]]
        /// baseName → every era containing it. The songKey-less fallback for
        /// both `resolvedSong` and `crossEraRefs`, so neither has to rescan
        /// the tracker (Era.allSongs rebuilds its array on each access).
        let baseNameEras: [String: [CrossEraRef]]
        /// Name key (Song.nameKey) → every song with that title, or that name
        /// as one part of a slash title; and → every song listing it as an alt
        /// title. Back `linkedRefs`, the picker's "Also Known As" row.
        let titleKeySongs: [String: [CrossEraRef]]
        let altTitleKeySongs: [String: [CrossEraRef]]
        let eraOrder: [String: Int]
        /// Per-era, per-song lowercased search haystack, built once off-main so each
        /// keystroke only compares. Shape mirrors `artist.eras[i].allSongs[j]`.
        let searchIndex: [[SongSearchFields]]
        /// Ordered playback contexts, one per era — what drives auto-advance into the
        /// next era. Built once off-main: it parses every version's link.
        let eraPlaybackContexts: [EraSongContext]

        init(artist: Artist) {
            var statsByName: [String: Stats] = [:]
            var total = 0, available = 0, snippets = 0, confirmed = 0, fullHQ = 0
            var keyEras: [String: [CrossEraRef]] = [:]
            var byBaseName: [String: [CrossEraRef]] = [:]
            var byTitleKey: [String: [CrossEraRef]] = [:]
            var byAltTitleKey: [String: [CrossEraRef]] = [:]
            for era in artist.eras {
                let s = ArtistViewModel.computeEraStats(era)
                statsByName[era.name] = s
                total += s.total
                available += s.available
                snippets += s.snippets
                confirmed += s.confirmed
                fullHQ += s.fullHQ
                for song in era.allSongs {
                    // Before the placeholder guard: a "???" row's alt title is its only identity and
                    // still links to the named song (never BY the placeholder title).
                    let linkRef = CrossEraRef(eraName: era.name, eraArt: era.artUrl, song: song)
                    for key in song.titleKeys { byTitleKey[key, default: []].append(linkRef) }
                    for key in song.altTitleKeys { byAltTitleKey[key, default: []].append(linkRef) }
                    // A placeholder title identifies nothing: indexing it would group every
                    // unidentified track under one key. Mirrors the backend's empty songKey.
                    guard !song.isPlaceholder else { continue }
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
            var tabStats: [String: Stats] = [:]
            for tab in artist.tabs ?? [] {
                tabStats[tab.id] = ArtistViewModel.computeTabStats(tab.entries)
            }
            self.tabStatsByKey = tabStats
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
            self.titleKeySongs = byTitleKey
            self.altTitleKeySongs = byAltTitleKey
            self.eraOrder = Dictionary(
                artist.eras.enumerated().map { ($1.name, $0) }, uniquingKeysWith: { first, _ in first }
            )
            self.searchIndex = artist.eras.map { $0.allSongs.map(SongSearchFields.init(song:)) }
            self.eraPlaybackContexts = artist.eras.map { era in
                EraSongContext(
                    eraName: era.name,
                    artistName: artist.name,
                    artUrl: era.artUrl ?? "",
                    versions: era.allSongs.flatMap(\.versions).filter(\.isStreamable),
                    artistSlug: artist.slug
                )
            }
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

    /// Every era containing this payload's song. Prefers `songKey` (only songs
    /// spanning >1 era), falling back to the base-name index, which covers the rest.
    ///
    /// A nil `payload.song` (Now Playing, Favourites) still resolves via the
    /// version's `derivedBaseName`, the key the base-name index is built on.
    func crossEraRefs(for payload: SongDetailPayload) -> [CrossEraRef] {
        if let payloadSong = payload.song {
            if let key = payloadSong.songKey, !key.isEmpty, let refs = songKeyEras[key] {
                return refs
            }
            guard !payloadSong.isPlaceholder else { return [] }
            return baseNameEras[payloadSong.baseName] ?? []
        }
        let derived = payload.version.derivedBaseName
        guard !Song.isPlaceholderName(derived) else { return [] }
        return baseNameEras[derived] ?? []
    }

    /// Songs linked to this payload's song by name, one hop: a song whose title is one
    /// of this song's names (title, slash-title part, alt title), or one listing this
    /// song's title as an alt title. Linked, never merged; excludes the song's own eras.
    /// See docs/decisions.md::parser.py::_reconcile_title_misreads.
    func linkedRefs(for payload: SongDetailPayload) -> [CrossEraRef] {
        let family = crossEraRefs(for: payload)
        let ownSongs = family.isEmpty ? payload.song.map { [$0] } ?? [] : family.map(\.song)
        var titles: Set<String> = []
        var names: Set<String> = []
        if ownSongs.isEmpty {
            // A bare version (Now Playing, Favourites): its own name and aliases.
            if !Song.isPlaceholderName(payload.version.derivedBaseName) {
                titles = Song.nameKeys(ofTitle: payload.version.derivedBaseName)
            }
            names = titles
            for alt in payload.version.altTitles ?? [] {
                names.formUnion(Song.nameKeys(ofTitle: alt))
            }
        } else {
            for song in ownSongs {
                titles.formUnion(song.titleKeys)
                names.formUnion(song.titleKeys)
                names.formUnion(song.altTitleKeys)
            }
        }

        func identity(_ ref: CrossEraRef) -> String {
            "\(ref.eraName)::\(ref.song.baseName)::\(ref.song.allVersions.first?.id ?? "")"
        }
        var seen = Set(family.map(identity))
        if let own = payload.song {
            seen.insert(identity(CrossEraRef(eraName: payload.eraName, eraArt: payload.eraArt, song: own)))
        }
        var linked: [CrossEraRef] = []
        for key in names {
            for ref in titleKeySongs[key] ?? [] where seen.insert(identity(ref)).inserted {
                linked.append(ref)
            }
        }
        for key in titles {
            for ref in altTitleKeySongs[key] ?? [] where seen.insert(identity(ref)).inserted {
                linked.append(ref)
            }
        }
        // Set iteration order is random; era order, then title, is stable.
        linked.sort {
            let (a, b) = (eraOrder[$0.eraName] ?? .max, eraOrder[$1.eraName] ?? .max)
            return a != b ? a < b : $0.song.baseName < $1.song.baseName
        }
        // ponytail: cap the row rather than rank; a generic alias ("Intro") names dozens of songs.
        return Array(linked.prefix(Self.maxLinkedSongs))
    }

    nonisolated static let maxLinkedSongs = 24

    /// How many era covers are warmed before the artist screen is pushed: about two
    /// screenfuls of collapsed cards, without a 40-era tracker waiting on 40 downloads.
    static let coldStartArtCount = 8

    /// Preferred construction path: the stats/content pass runs off-main.
    ///
    /// `warmArt` pulls the first few era covers (and their colours) into the cache
    /// while the landing spinner still shows, so the first cards don't pop in grey.
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

    /// Load era covers into the image cache and derive their display colours (bytes
    /// alone would still leave cards grey for a frame).
    ///
    /// `limit` nil warms every era (the background pass from ArtistView).
    func warmEraArt(limit: Int? = nil) async {
        let eras = limit.map { Array(artist.eras.prefix($0)) } ?? artist.eras
        // Keyed on the cover, not the era: sibling eras can share one, and the result
        // is applied to every era using that URL below.
        var seenArt = Set<String>()
        let targets: [(artUrl: String, url: URL)] = eras.compactMap { era in
            guard let art = era.artUrl,
                  eraDisplay[era.name] == nil,
                  seenArt.insert(art).inserted,
                  let url = APIClient.shared.imageProxyURL(for: art, width: 320)
            else { return nil }
            return (art, url)
        }
        guard !targets.isEmpty else { return }

        await withTaskGroup(of: (String, Color)?.self) { group in
            // Enough to saturate the link without starving the cover the user
            // is looking at.
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
        self.tabStatsByKey = precomputed.tabStatsByKey
        self.artistStats = precomputed.artistStats
        self.content = precomputed.content
        self.songKeyEras = precomputed.songKeyEras
        self.baseNameEras = precomputed.baseNameEras
        self.titleKeySongs = precomputed.titleKeySongs
        self.altTitleKeySongs = precomputed.altTitleKeySongs
        self.eraOrder = precomputed.eraOrder
        self.searchIndex = precomputed.searchIndex
        self.eraPlaybackContexts = precomputed.eraPlaybackContexts

        // Seed era colors from persisted cache — see DECISIONS.md::EraColorExtractor.swift::cache-key
        let cached = EraColorExtractor.cachedColors()
        for era in artist.eras {
            guard let artUrl = era.artUrl, let color = cached[artUrl] else { continue }
            eraDisplay[era.name] = EraDisplayColors.derive(from: color, in: colorScheme)
        }

        rebuildEraRows()
    }

    // MARK: - Era colors

    /// Re-derive every cached era colour for a new appearance. No-op when the
    /// scheme is unchanged, so it is safe to call from `onChange`. The raw
    /// dominant colours are appearance-independent, so nothing is re-extracted.
    func setColorScheme(_ scheme: ColorScheme) {
        guard scheme != colorScheme else { return }
        colorScheme = scheme
        eraDisplay = eraDisplay.mapValues { EraDisplayColors.derive(from: $0.dominant, in: scheme) }
    }

    /// Idempotent — extraction is deterministic and cached, so the first
    /// derivation per era wins and later callbacks are no-ops. Buffers into
    /// `pendingEraColors` and coalesces same-turn callbacks into a single
    /// `eraDisplay` write on the next runloop tick.
    func setEraColor(eraName: String, dominant: Color) {
        guard eraDisplay[eraName] == nil, pendingEraColors[eraName] == nil else { return }
        pendingEraColors[eraName] = EraDisplayColors.derive(from: dominant, in: colorScheme)
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
                // Ordinals are positions within the FILTERED era, so a filter change renumbers
                // them and the expanded set must reset.
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

    /// Set (or clear) the single expanded era outright, whatever was open before
    /// (`toggleEra` flips).
    func openEra(_ name: String?) {
        guard !isBadgeFilterActive, expandedEra != name else { return }
        expandedEra = name
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
                                group: section.group, notes: section.notes
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
                // `versions` (what matched the filter): the array the row's count and chevron use.
                // Playback context uses `allVersions` elsewhere, so auto-advance is unaffected.
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
