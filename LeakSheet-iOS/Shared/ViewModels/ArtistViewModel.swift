import Foundation
import SwiftUI
import Observation

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
    let eraStatsByName: [String: Stats]
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
    internal(set) var debouncedQuery: String = ""
    var debounceTask: Task<Void, Never>?

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
    /// Selected content-tab id (TabSection.id): a strict switch, not a peer filter. Only
    /// that tab's entries show, one chip per parsed tab.
    internal(set) var selectedTabKey: String? = nil
    var expandedEra: String? = nil
    /// Expanded multi-version songs, keyed "eraName::baseName". Lives here
    /// (not view @State) because lazy containers discard offscreen state.
    internal(set) var expandedSongs: Set<String> = []

    // MARK: - Pipeline output

    internal(set) var content: FilteredContent
    /// True while a filter change is being computed off-main. Chips flip
    /// instantly; the list keeps the previous content until the new one lands.
    internal(set) var isFiltering = false
    var filterTask: Task<Void, Never>?

    /// Flattened rows for the eras branch — rebuilt on content/expansion
    /// changes so `body` only iterates.
    internal(set) var eraRows: [EraRow] = []

    /// The appearance the cached `eraDisplay` values were derived for; switching
    /// re-derives them (the dominant colours are appearance-independent).
    internal(set) var colorScheme: ColorScheme = .dark

    /// songKey → eras containing that song (only keys spanning >1 era) —
    /// built once in Precomputed.
    let songKeyEras: [String: [CrossEraRef]]
    /// baseName → every era containing it (see Precomputed.baseNameEras).
    let baseNameEras: [String: [CrossEraRef]]
    /// Name key → songs carrying it as a title / as an alt title (see
    /// Precomputed.titleKeySongs), and each era's position for ordering.
    let titleKeySongs: [String: [CrossEraRef]]
    let altTitleKeySongs: [String: [CrossEraRef]]
    let eraOrder: [String: Int]
    /// Producer and feature credits by name key (see Precomputed.creditIndex).
    let creditIndex: [CreditRole: [String: [CreditHit]]]
    let creditDisplayNames: [String: String]

    /// Prebuilt lowercased search haystack (see Precomputed.searchIndex).
    let searchIndex: [[SongSearchFields]]
    /// Every era's streamable versions, in tracker order (see Precomputed.eraPlaybackContexts).
    let allEraPlaybackContexts: [EraSongContext]
    /// Era rollover order for the current filters: a chip that hides songs hides them from
    /// auto-advance too. Views re-register whenever `eraPlaybackRevision` changes.
    internal(set) var eraPlaybackContexts: [EraSongContext]
    internal(set) var eraPlaybackRevision = 0
    var eraPlaybackIsFiltered = false

    // MARK: - Recents windowing

    internal(set) var visibleRecents: [RecentResult] = []
    static let recentsPageSize = 60

    // MARK: - Era display colors

    /// Derived display colors per era, computed once per extracted color.
    internal(set) var eraDisplay: [String: EraDisplayColors] = [:]
    /// Colors derived since the last flush, so a burst of extractions lands as one
    /// `eraDisplay` write (per-card writes trip the glassEffect multiple-updates fault).
    var pendingEraColors: [String: EraDisplayColors] = [:]
    var eraColorFlushScheduled = false

    var isSearching: Bool { !debouncedQuery.isEmpty }

    /// Badge-annotation kinds: never pages. Older cached payloads may still carry them.
    private static let badgeTabKinds: Set<String> = [
        "best_of", "worst_of", "special", "grails", "wanted",
    ]

    /// Parsed content tabs (Misc / Music Videos / Released / Stems / …), one
    /// switchable chip each.
    var availableTabs: [TabSection] {
        (artist.tabs ?? []).filter { !Self.badgeTabKinds.contains($0.kind) }
    }

    /// Display name of the selected content tab, for anything that has to name
    /// the page — nil on the song tree.
    var selectedTabName: String? {
        guard let key = selectedTabKey else { return nil }
        return availableTabs.first { $0.id == key }?.name
    }

    // MARK: - Init

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
        self.creditIndex = precomputed.creditIndex
        self.creditDisplayNames = precomputed.creditDisplayNames
        self.searchIndex = precomputed.searchIndex
        self.allEraPlaybackContexts = precomputed.eraPlaybackContexts
        self.eraPlaybackContexts = precomputed.eraPlaybackContexts

        // Seed era colors from persisted cache — see DECISIONS.md::EraColorExtractor.swift::cache-key
        let cached = EraColorExtractor.cachedColors()
        for era in artist.eras {
            guard let artUrl = era.artUrl, let color = cached[artUrl] else { continue }
            eraDisplay[era.name] = EraDisplayColors.derive(from: color, in: colorScheme)
        }

        rebuildEraRows()
    }

}
