import Foundation

// MARK: - Artist

nonisolated struct Artist: Codable, Identifiable, Hashable, Sendable {
    let name: String
    let slug: String
    let sourceUrl: String?
    let eras: [Era]
    let trackerStats: TrackerStats?
    let notices: [Notice]?
    let totalSongs: Int?
    let totalVersions: Int?
    /// Entries from secondary Misc / Music Videos tabs; optional so older payloads decode.
    /// All parsed secondary tabs (misc, music_videos, released, best_of,
    /// worst_of, stems, other) — the uniform switchable-mode surface.
    let tabs: [TabSection]?

    var id: String { slug }

    var computedTotalSongs: Int {
        totalSongs ?? eras.reduce(0) { $0 + $1.computedSongCount }
    }

    var computedTotalVersions: Int {
        totalVersions ?? eras.reduce(0) { $0 + $1.computedVersionCount }
    }

    enum CodingKeys: String, CodingKey {
        case name, slug, eras, notices, tabs
        case sourceUrl = "source_url"
        case trackerStats = "tracker_stats"
        case totalSongs = "total_songs"
        case totalVersions = "total_versions"
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(slug)
    }

    static func == (lhs: Artist, rhs: Artist) -> Bool {
        lhs.slug == rhs.slug
    }
}

// MARK: - Era

nonisolated struct Era: Codable, Identifiable, Hashable, Sendable {
    let name: String
    let altNames: [String]?
    let description: String?
    let timeline: [TimelineEvent]?
    let artUrl: String?
    let sections: [Section]?
    let songCount: Int?
    let versionCount: Int?
    /// The sheet's own counts from the era header (86% of eras); nil when it has none.
    var stats: EraStats? = nil

    var id: String { name }

    var allSongs: [Song] {
        sections?.flatMap(\.songs) ?? []
    }

    var computedSongCount: Int {
        songCount ?? allSongs.count
    }

    var computedVersionCount: Int {
        versionCount ?? allSongs.reduce(0) { $0 + $1.versions.count }
    }

    enum CodingKeys: String, CodingKey {
        case name, description, timeline, sections
        case altNames = "alt_names"
        case artUrl = "art_url"
        case songCount = "song_count"
        case versionCount = "version_count"
        case stats
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(name)
    }

    static func == (lhs: Era, rhs: Era) -> Bool {
        lhs.name == rhs.name
    }
}

/// Counts the tracker states in an era's header cell, mirroring the backend's `EraStats`.
nonisolated struct EraStats: Codable, Hashable, Sendable {
    let ogFiles: Int?
    let full: Int?
    let totalFull: Int?
    let tagged: Int?
    let partial: Int?
    let snippets: Int?
    let stemBounces: Int?
    let unavailable: Int?
    /// A total the sheet states outright ("18 Total"); 0 when it states none.
    let statedTotal: Int?
    /// The backend's derived total: the stated one, else the sum of the status counts.
    let total: Int?
    /// Discography-style counts in the sheet's own wording, e.g. ["singles": 4].
    let releaseTypes: [String: Int]?

    enum CodingKeys: String, CodingKey {
        case full, tagged, partial, snippets, unavailable, total
        case ogFiles = "og_files"
        case totalFull = "total_full"
        case stemBounces = "stem_bounces"
        case statedTotal = "stated_total"
        case releaseTypes = "release_types"
    }
}

// MARK: - Section

nonisolated struct Section: Codable, Identifiable, Hashable, Sendable {
    let name: String
    let group: String?
    let songs: [Song]
    /// Text on the sheet's label row — usually a sub-era timeline.
    var notes: String? = nil

    var id: String { name + (group ?? "") }

    func hash(into hasher: inout Hasher) {
        hasher.combine(name)
        hasher.combine(group)
    }

    static func == (lhs: Section, rhs: Section) -> Bool {
        lhs.name == rhs.name && lhs.group == rhs.group
    }
}

// MARK: - Song

nonisolated struct Song: Codable, Identifiable, Hashable, Sendable {
    let baseName: String
    /// Stable normalized identity shared by the same song across eras;
    /// empty/nil for unidentified placeholder tracks and older payloads.
    let songKey: String?
    let versions: [SongVersion]
    let badge: String?
    /// Every version the tracker lists, including ones the active filter hid.
    /// Nil when never filtered (and after decode: it is excluded from CodingKeys).
    var unfilteredVersions: [SongVersion]? = nil

    /// The full version set — what expansion, the detail sheet, and the
    /// auto-advance queue must use. Falls back to `versions` when unfiltered.
    var allVersions: [SongVersion] { unfilteredVersions ?? versions }

    var id: String { baseName }

    var primary: SongVersion? { versions.first }

    /// Names the fanbase uses for an unidentified track. Mirrors the backend's
    /// `_PLACEHOLDER_BASE_NAMES`: such rows are distinct tracks, sent with an empty `songKey`.
    static let placeholderBaseNames: Set<String> = [
        "???", "??", "?", "unknown", "untitled", "tba", "n/a",
    ]

    /// True when this song's title identifies nothing — see above.
    var isPlaceholder: Bool {
        Self.isPlaceholderName(baseName)
    }

    static func isPlaceholderName(_ name: String) -> Bool {
        placeholderBaseNames.contains(
            name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        )
    }

    var computedBadge: Badge? {
        if let b = badge { return Badge(rawValue: b) }
        return Badge.mostSignificant(in: versions)
    }

    /// Whether the row shows more than one version — the *displayed* set, matching the
    /// row's "N versions" label. Playback and the description sheet use `allVersions`.
    var hasMultipleVersions: Bool {
        versions.count > 1
    }

    /// Ranks used to pick the version whose badges best summarize a collapsed
    /// multi-version row (highest quality wins, availability breaks ties).
    private static let qualityRank: [String: Int] = [
        "Lossless": 6, "CD Quality": 5, "High Quality": 4,
        "Recording": 3, "Low Quality": 2, "Not Available": 0,
    ]
    private static let availabilityRank: [String: Int] = [
        "OG File": 8, "Full": 7, "Tagged": 6, "Partial": 5,
        "Snippet": 4, "Stem Bounce": 3, "Beat Only": 2, "Confirmed": 1,
    ]

    /// The version with the best quality (availability breaks ties) — what a
    /// collapsed multi-version row shows so the song can be judged at a
    /// glance without expanding.
    var bestVersion: SongVersion? {
        Self.best(of: versions)
    }

    /// The version a collapsed row represents: the best playable one, else the best
    /// overall, so the row's badges describe what tapping it plays.
    var bestPlayableVersion: SongVersion? {
        Self.best(of: versions.filter(\.isStreamable)) ?? bestVersion
    }

    private static func best(of candidates: [SongVersion]) -> SongVersion? {
        candidates.max { a, b in
            let qa = Self.qualityRank[a.quality ?? ""] ?? 1
            let qb = Self.qualityRank[b.quality ?? ""] ?? 1
            if qa != qb { return qa < qb }
            let aa = Self.availabilityRank[a.availableLength ?? ""] ?? 0
            let ab = Self.availabilityRank[b.availableLength ?? ""] ?? 0
            return aa < ab
        }
    }

    enum CodingKeys: String, CodingKey {
        case versions, badge
        case baseName = "base_name"
        case songKey = "song_key"
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(baseName)
    }

    static func == (lhs: Song, rhs: Song) -> Bool {
        lhs.baseName == rhs.baseName && lhs.versions == rhs.versions
    }
}

// MARK: - Song version-filter helper

extension Song {
    /// Returns a copy of this song with only versions matching `filter`, or nil if none match.
    /// Nonisolated: called from the off-main filter pipeline.
    nonisolated func withFilteredVersions(_ filter: (SongVersion) -> Bool) -> Song? {
        let kept = versions.filter(filter)
        guard !kept.isEmpty else { return nil }
        // Kept-version badge — see DECISIONS.md::Models.swift::kept-badge
        let keptBadge = Badge.mostSignificant(in: kept)?.rawValue ?? badge
        // Carry the full set forward so the row can still expand to every
        // version and the detail sheet can still queue the whole song.
        return Song(
            baseName: baseName, songKey: songKey, versions: kept, badge: keptBadge,
            unfilteredVersions: unfilteredVersions ?? versions
        )
    }
}

// MARK: - Song names

extension Song {
    /// A title's identity for linking and search: case, diacritics and
    /// punctuation don't count, so "Stay On 'Em", "stay on em" and "Stay On Em"
    /// are one name. A name that is nothing but punctuation ("???") keeps its
    /// lowercased text, so it can still be searched for.
    /// See docs/decisions.md::parser.py::_reconcile_title_misreads.
    nonisolated static func nameKey(_ name: String) -> String {
        let folded = name.folding(options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive], locale: nil)
        var key = ""
        var pendingSpace = false
        for character in folded {
            if "'\u{2018}\u{2019}".contains(character) { continue }  // "Don't" matches "Dont"
            if character.isWhitespace || ",.:;!?\"\u{201C}\u{201D}".contains(character) {
                pendingSpace = !key.isEmpty
                continue
            }
            if pendingSpace { key.append(" ") }
            pendingSpace = false
            key.append(character)
        }
        return key.isEmpty ? name.lowercased().trimmingCharacters(in: .whitespaces) : key
    }

    /// The keys a title stands for: the whole title plus each part of a slash
    /// title, since "Stay On Em / Precious" is both songs' name.
    nonisolated static func nameKeys(ofTitle title: String) -> Set<String> {
        var keys: Set<String> = [nameKey(title)]
        let parts = title.components(separatedBy: " / ")
        if parts.count > 1 {
            keys.formUnion(parts.map(nameKey))
        }
        keys.remove("")
        return keys
    }

    /// This song's own title keys. A placeholder title identifies nothing.
    nonisolated var titleKeys: Set<String> {
        isPlaceholder ? [] : Self.nameKeys(ofTitle: baseName)
    }

    /// Keys of every alt title any version lists.
    nonisolated var altTitleKeys: Set<String> {
        var keys: Set<String> = []
        for version in allVersions {
            for alt in version.altTitles ?? [] {
                keys.formUnion(Self.nameKeys(ofTitle: alt))
            }
        }
        return keys
    }
}

// MARK: - SongVersion

// MARK: - MiscEntry

// MARK: - TabSection

// MARK: - Badge

// MARK: - TrackerStats

// MARK: - Notice

// MARK: - TimelineEvent

// MARK: - DiscoveryArtist
