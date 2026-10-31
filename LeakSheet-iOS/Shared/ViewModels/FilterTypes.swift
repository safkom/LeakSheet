import Foundation

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
    // Names and groups repeat within an era: headers are keyed by which occurrence they are,
    // which a filter hiding other sections does not renumber.
    case groupHeader(text: String, eraName: String, occurrence: Int)
    case sectionHeader(name: String, eraName: String, group: String?, occurrence: Int, notes: String? = nil)
    // `ordinal` disambiguates same-baseName songs — see DECISIONS.md::ArtistViewModel.swift::song-ordinal
    case song(Song, eraName: String, eraArt: String?, expanded: Bool, hasMultiple: Bool, isLast: Bool, ordinal: Int)
    case version(SongVersion, index: Int, song: Song, eraName: String, eraArt: String?, isLast: Bool, songOrdinal: Int)
    case eraGap(eraName: String)

    var id: String {
        switch self {
        case .card(let filtered, _): return "card::\(filtered.era.name)"
        case .divider(let era): return "div::\(era)"
        case .groupHeader(let text, let era, let nth): return "grp::\(era)::\(text)::\(nth)"
        case .sectionHeader(let name, let era, let group, let nth, _):
            return "sec::\(era)::\(group ?? "")::\(name)::\(nth)"
        case .song(let song, let era, _, _, _, _, let ord): return "song::\(era)::\(ord)::\(song.baseName)"
        case .version(let version, let index, let song, let era, _, _, let songOrd):
            return "ver::\(era)::\(songOrd)::\(song.baseName)::\(version.id)::\(index)"
        case .eraGap(let era): return "gap::\(era)"
        }
    }
}
