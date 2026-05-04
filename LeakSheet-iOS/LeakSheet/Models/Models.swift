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

    var id: String { slug }

    var computedTotalSongs: Int {
        totalSongs ?? eras.reduce(0) { $0 + $1.computedSongCount }
    }

    var computedTotalVersions: Int {
        totalVersions ?? eras.reduce(0) { $0 + $1.computedVersionCount }
    }

    enum CodingKeys: String, CodingKey {
        case name, slug, eras, notices
        case sourceUrl = "source_url"
        case trackerStats = "tracker_stats"
        case parseMetadata = "parse_metadata"
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

    enum CodingKeys: String, CodingKey {
        case versions, badge, quality
        case baseName = "base_name"
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
    func withFilteredVersions(_ filter: (SongVersion) -> Bool) -> Song? {
        let kept = versions.filter(filter)
        guard !kept.isEmpty else { return nil }
        // Uses the synthesized memberwise initializer
        return Song(
            baseName: baseName, versions: kept, badge: badge,
            availableLength: availableLength, quality: quality,
            trackLength: trackLength, leakDate: leakDate, fileDate: fileDate
        )
    }
}

// MARK: - SongVersion

nonisolated struct SongVersion: Codable, Identifiable, Hashable, Sendable {
    let name: String
    let versionTag: String?
    let badge: String?
    let featuring: String?
    let producers: String?
    let collaboration: String?
    let refs: String?
    let altTitles: [String]?
    let notes: String?
    let ogFilename: String?
    let samples: [String]?
    let trackLength: String?
    let fileDate: String?
    let leakDate: String?
    let availableLength: String?
    let quality: String?
    let links: [String]?
    let qualityColor: String?
    let availableLengthColor: String?
    let dateOfRecording: String?
    let type: String?

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
        if let og = ogFilename, Self.pathHasNonAudioExtension(og) { return false }
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

    enum CodingKeys: String, CodingKey {
        case name, badge, featuring, producers, collaboration, refs, notes, samples, quality, links, type
        case versionTag = "version_tag"
        case altTitles = "alt_titles"
        case ogFilename = "og_filename"
        case trackLength = "track_length"
        case fileDate = "file_date"
        case leakDate = "leak_date"
        case availableLength = "available_length"
        case qualityColor = "quality_color"
        case availableLengthColor = "available_length_color"
        case dateOfRecording = "date_of_recording"
    }
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

nonisolated struct DiscoveryArtist: Codable, Identifiable, Sendable {
    let name: String
    let url: String
    let credit: String?
    let linksWork: Int?
    let updated: Int?
    let best: Bool?

    var id: String { url }

    enum CodingKeys: String, CodingKey {
        case name, url, credit, best, updated
        case linksWork = "links_work"
    }
}
