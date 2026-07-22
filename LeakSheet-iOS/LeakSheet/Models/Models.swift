import Foundation

// MARK: - Artist

nonisolated struct Artist: Codable, Identifiable, Hashable, Sendable {
    let name: String
    let slug: String
    let sourceUrl: String?
    let eras: [Era]
    let trackerStats: TrackerStats?
    let parseMetadata: ParseMetadata?
    let notices: [Notice]?
    let totalSongs: Int?
    let totalVersions: Int?
    /// Entries from secondary Misc / Music Videos tabs — optional so older
    /// cached responses and servers decode fine (ogFilenames precedent).
    let miscEntries: [MiscEntry]?
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
        case parseMetadata = "parse_metadata"
        case totalSongs = "total_songs"
        case totalVersions = "total_versions"
        case miscEntries = "misc_entries"
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
    let statsRaw: String?
    let stats: EraStats?
    let artUrl: String?
    let highlightedProducers: [String]?
    let sections: [Section]?
    let songCount: Int?
    let versionCount: Int?

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
        case name, description, timeline, stats, sections
        case altNames = "alt_names"
        case statsRaw = "stats_raw"
        case artUrl = "art_url"
        case highlightedProducers = "highlighted_producers"
        case songCount = "song_count"
        case versionCount = "version_count"
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(name)
    }

    static func == (lhs: Era, rhs: Era) -> Bool {
        lhs.name == rhs.name
    }
}

// MARK: - Section

nonisolated struct Section: Codable, Identifiable, Hashable, Sendable {
    let name: String
    let group: String?
    let songs: [Song]

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
    let availableLength: String?
    let quality: String?
    let trackLength: String?
    let leakDate: String?
    let fileDate: String?

    var id: String { baseName }

    var primary: SongVersion? { versions.first }

    var computedBadge: Badge? {
        if let b = badge { return Badge(rawValue: b) }
        for v in versions {
            if let b = v.badge { return Badge(rawValue: b) }
        }
        return nil
    }

    var isStreamable: Bool {
        versions.contains { $0.isStreamable }
    }

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
        versions.max { a, b in
            let qa = Self.qualityRank[a.quality ?? ""] ?? 1
            let qb = Self.qualityRank[b.quality ?? ""] ?? 1
            if qa != qb { return qa < qb }
            let aa = Self.availabilityRank[a.availableLength ?? ""] ?? 0
            let ab = Self.availabilityRank[b.availableLength ?? ""] ?? 0
            return aa < ab
        }
    }

    enum CodingKeys: String, CodingKey {
        case versions, badge, quality
        case baseName = "base_name"
        case songKey = "song_key"
        case availableLength = "available_length"
        case trackLength = "track_length"
        case leakDate = "leak_date"
        case fileDate = "file_date"
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
        // Uses the synthesized memberwise initializer
        return Song(
            baseName: baseName, songKey: songKey, versions: kept, badge: badge,
            availableLength: availableLength, quality: quality,
            trackLength: trackLength, leakDate: leakDate, fileDate: fileDate
        )
    }
}

// MARK: - SongVersion

/// A labeled evidence link from a tracker's Sources column — provenance for
/// how a leak is known ("First Mention (Screenshot)"), distinct from listen links.
nonisolated struct SourceRef: Codable, Hashable, Sendable {
    let label: String
    let url: String
}

nonisolated struct SongVersion: Codable, Identifiable, Hashable, Sendable {
    let name: String
    let versionTag: String?
    let badge: String?
    let featuring: String?
    let producers: String?
    let collaboration: String?
    let refs: String?
    /// Performer from a dedicated Artist / Credited Artist column (collab-style
    /// trackers) — distinct from `featuring`; added backend-side 2026-07-20.
    let creditedArtists: String?
    let altTitles: [String]?
    let notes: String?
    let ogFilename: String?
    let ogFilenames: [String]?
    let samples: [String]?
    let trackLength: String?
    let fileDate: String?
    let leakDate: String?
    let availableLength: String?
    let quality: String?
    let links: [String]?
    let dateOfRecording: String?
    let type: String?
    /// Labeled evidence links (Sources column, Travis-style trackers).
    /// Optional so payloads persisted before the field existed still decode.
    let sources: [SourceRef]?
    /// Fan star rating 1-5 extracted from the availability cell.
    let rating: Int?

    var id: String { "\(name)::\(versionTag ?? "")" }

    /// File extensions that identify the linked file as NOT a playable audio stream.
    /// Marking a version as non-streamable hides Play actions and shows the
    /// description sheet instead of attempting playback.
    static let nonAudioExtensions: [String] = [
        ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz",
        ".pdf", ".txt", ".doc", ".docx", ".rtf",
        ".exe", ".dmg", ".iso", ".pkg",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
        ".mp4", ".mov", ".mkv", ".avi", ".webm"
    ]

    private static func pathHasNonAudioExtension(_ path: String) -> Bool {
        let lower = path.lowercased()
        return SongVersion.nonAudioExtensions.contains(where: lower.hasSuffix)
    }

    var isStreamable: Bool {
        if allOgFilenames.contains(where: Self.pathHasNonAudioExtension) { return false }
        guard let link = streamableLink else { return false }
        if let urlPath = URL(string: link)?.path, Self.pathHasNonAudioExtension(urlPath) {
            return false
        }
        return true
    }

    var streamableLink: String? {
        guard let links else { return nil }
        return links.first { StreamResolver.isStreamableURL($0) }
    }

    /// Base song name with the version tag stripped — matches the parser's
    /// `Song.base_name` so favourites keyed from a bare version (player,
    /// description sheet) agree with keys written from song rows. Tolerates
    /// trailing whitespace and tag-case differences.
    var derivedBaseName: String {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard let tag = versionTag else { return trimmed }
        let suffix = " [\(tag)]"
        if trimmed.hasSuffix(suffix) {
            return String(trimmed.dropLast(suffix.count)).trimmingCharacters(in: .whitespaces)
        }
        if trimmed.lowercased().hasSuffix(suffix.lowercased()) {
            return String(trimmed.dropLast(suffix.count)).trimmingCharacters(in: .whitespaces)
        }
        return trimmed
    }

    /// All OG filenames — prefers the plural field, falls back to the legacy
    /// singular one for responses from older backends.
    var allOgFilenames: [String] {
        if let list = ogFilenames, !list.isEmpty { return list }
        if let single = ogFilename, !single.isEmpty { return [single] }
        return []
    }

    enum CodingKeys: String, CodingKey {
        case name, badge, featuring, producers, collaboration, refs, notes, samples, quality, links, type, sources, rating
        case creditedArtists = "credited_artists"
        case versionTag = "version_tag"
        case altTitles = "alt_titles"
        case ogFilename = "og_filename"
        case ogFilenames = "og_filenames"
        case trackLength = "track_length"
        case fileDate = "file_date"
        case leakDate = "leak_date"
        case availableLength = "available_length"
        case dateOfRecording = "date_of_recording"
    }
}

// MARK: - MiscEntry

/// One entry from a secondary tracker tab (Misc / Music Videos) — kept fully
/// separate from the era/song tree.
nonisolated struct MiscEntry: Codable, Identifiable, Hashable, Sendable {
    let eraName: String
    let name: String
    let notes: String?
    let entryType: String?
    let date: String?
    let length: String?
    let available: String?
    let quality: String?
    let streaming: Bool?
    let links: [String]
    let sourceTab: String

    var id: String { "\(sourceTab)::\(eraName)::\(name)::\(date ?? "")" }

    var streamableLink: String? {
        links.first { StreamResolver.isStreamableURL($0) }
    }

    var isStreamable: Bool { streamableLink != nil }

    /// Every link, classified by content kind — lets a row show the right
    /// affordance per link and, when there's more than one, let the user
    /// choose explicitly instead of guessing which one to open.
    var mediaLinks: [MiscLink] {
        links.map { url in
            let kind = MiscLinkClassifier.classify(url)
            return MiscLink(url: url, kind: kind, label: MiscLinkClassifier.label(for: url, kind: kind))
        }
    }

    /// Best available preview image across this entry's links — a direct
    /// image file, or a derivable video thumbnail (YouTube). Nil when
    /// nothing can be previewed without fetching the linked page.
    var previewImageURL: String? {
        mediaLinks.lazy.compactMap { MiscLinkClassifier.thumbnailURL(for: $0.url, kind: $0.kind) }.first
    }

    /// Minimal SongVersion so misc entries flow through the existing playback
    /// and description-sheet machinery unchanged.
    var asSongVersion: SongVersion {
        SongVersion(
            name: name,
            versionTag: nil,
            badge: nil,
            featuring: nil,
            producers: nil,
            collaboration: nil,
            refs: nil,
            creditedArtists: nil,
            altTitles: nil,
            notes: notes,
            ogFilename: nil,
            ogFilenames: nil,
            samples: nil,
            trackLength: length,
            fileDate: nil,
            leakDate: date,
            availableLength: available,
            quality: quality,
            links: links,
            dateOfRecording: nil,
            type: entryType,
            sources: nil,
            rating: nil
        )
    }

    enum CodingKeys: String, CodingKey {
        case name, notes, date, length, available, quality, streaming, links
        case eraName = "era_name"
        case entryType = "entry_type"
        case sourceTab = "source_tab"
    }
}

// MARK: - TabSection

/// One parsed secondary tab (Released / Best Of / Worst Of / Stems / Misc /
/// Music Videos / other) — the uniform switchable-mode surface. Misc/MV
/// entries also remain in the flat `Artist.miscEntries` for backward compat.
nonisolated struct TabSection: Codable, Identifiable, Hashable, Sendable {
    let kind: String
    /// Original tab display name from the spreadsheet (may include emoji).
    let name: String
    let entries: [MiscEntry]

    var id: String { "\(kind)::\(name)" }
}

// MARK: - Badge

nonisolated enum Badge: String, Codable, CaseIterable, Sendable {
    case best
    case special
    case worst
    case grail
    case wanted
    case ai

    var emoji: String {
        switch self {
        case .best: "⭐"
        case .special: "✨"
        case .worst: "🗑️"
        case .grail: "🏆"
        case .wanted: "🏅"
        case .ai: "🤖"
        }
    }

    var isBestOf: Bool {
        self == .best || self == .special
    }
}

// MARK: - EraStats

nonisolated struct EraStats: Codable, Hashable, Sendable {
    let ogFiles: Int?
    let full: Int?
    let tagged: Int?
    let partial: Int?
    let snippets: Int?
    let stemBounces: Int?
    let unavailable: Int?
    let total: Int?

    enum CodingKeys: String, CodingKey {
        case full, tagged, partial, snippets, unavailable, total
        case ogFiles = "og_files"
        case stemBounces = "stem_bounces"
    }
}

// MARK: - TrackerStats

nonisolated struct TrackerStats: Codable, Hashable, Sendable {
    // Links
    let totalLinks: Int?
    let missingLinks: Int?
    let sourcesNeeded: Int?
    let notAvailableLinks: Int?
    // Quality
    let lossless: Int?
    let cdQuality: Int?
    let highQuality: Int?
    let lowQuality: Int?
    let recordings: Int?
    let notAvailableQuality: Int?
    // Availability
    let totalFull: Int?
    let ogFiles: Int?
    let stemBounces: Int?
    let full: Int?
    let tagged: Int?
    let partial: Int?
    let snippets: Int?
    let unavailable: Int?
    // Badges
    let bestOf: Int?
    let special: Int?
    let grails: Int?
    let wanted: Int?
    let worstOf: Int?

    enum CodingKeys: String, CodingKey {
        case lossless, full, tagged, partial, snippets, unavailable, recordings, special, wanted, grails
        case totalLinks = "total_links"
        case missingLinks = "missing_links"
        case sourcesNeeded = "sources_needed"
        case notAvailableLinks = "not_available_links"
        case cdQuality = "cd_quality"
        case highQuality = "high_quality"
        case lowQuality = "low_quality"
        case notAvailableQuality = "not_available_quality"
        case totalFull = "total_full"
        case ogFiles = "og_files"
        case stemBounces = "stem_bounces"
        case bestOf = "best_of"
        case worstOf = "worst_of"
    }
}

// MARK: - ParseMetadata

nonisolated struct ParseMetadata: Codable, Hashable, Sendable {
    let totalRows: Int?
    let songRows: Int?
    let skippedRows: Int?
    let unmatchedRows: [String]?
    let footerRows: Int?
    let fuzzyMatchedRows: Int?

    enum CodingKeys: String, CodingKey {
        case totalRows = "total_rows"
        case songRows = "song_rows"
        case skippedRows = "skipped_rows"
        case unmatchedRows = "unmatched_rows"
        case footerRows = "footer_rows"
        case fuzzyMatchedRows = "fuzzy_matched_rows"
    }
}

// MARK: - Notice

nonisolated struct Notice: Codable, Identifiable, Hashable, Sendable {
    let text: String
    let link: String?
    let kind: String?

    var id: String { text }

    var isAlert: Bool { kind == "alert" }
}

// MARK: - TimelineEvent

nonisolated struct TimelineEvent: Codable, Identifiable, Hashable, Sendable {
    let date: String
    let event: String

    var id: String { "\(date):\(event)" }
}

// MARK: - DiscoveryArtist

/// One entry of the backend /trackers discovery feed (TrackerHub sheet).
nonisolated struct DiscoveryArtist: Codable, Identifiable, Sendable {
    let name: String
    let url: String
    let credit: String?
    let best: Bool?
    let upToDate: Bool?
    let workingLinks: Bool?

    var id: String { url }

    enum CodingKeys: String, CodingKey {
        case name, url, credit, best
        case upToDate = "up_to_date"
        case workingLinks = "working_links"
    }
}
