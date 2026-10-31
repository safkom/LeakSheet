import Foundation

/// One entry from a secondary tracker tab (Misc / Music Videos) — kept fully
/// separate from the era/song tree.
nonisolated struct MiscEntry: Codable, Identifiable, Hashable, Sendable {
    let eraName: String
    /// Position within its tab, from the backend. Optional so payloads cached
    /// before the field existed still decode — see `id`.
    let rowIndex: Int?
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
    /// The tab's sub-section ("Instrumentals", "Music Videos"), if any.
    var section: String? = nil

    /// Row identity. `rowIndex` makes it unique: these tabs repeat content constantly,
    /// and ForEach keeps only the first row per duplicate id. Payloads cached before
    /// the backend sent an index fall back to the content-derived shape.
    var id: String {
        guard let rowIndex else {
            return "\(sourceTab)::\(eraName)::\(name)::\(date ?? "")"
        }
        return "\(sourceTab)::\(rowIndex)::\(eraName)::\(name)"
    }

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
            return MiscLink(url: url, kind: kind, label: MiscLinkClassifier.label(for: url))
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
            notes: notes,
            trackLength: length,
            leakDate: date,
            availableLength: available,
            quality: quality,
            streaming: streaming,
            links: links,
            type: entryType
        )
    }

    enum CodingKeys: String, CodingKey {
        case name, notes, date, length, available, quality, streaming, links, section
        case eraName = "era_name"
        case rowIndex = "row_index"
        case entryType = "entry_type"
        case sourceTab = "source_tab"
    }
}

/// One parsed secondary tab (Released / Best Of / Worst Of / Stems / Misc /
/// Music Videos / other) — the uniform switchable-mode surface.
nonisolated struct TabSection: Codable, Identifiable, Hashable, Sendable {
    let kind: String
    /// Original tab display name from the spreadsheet (may include emoji).
    let name: String
    let entries: [MiscEntry]

    var id: String { "\(kind)::\(name)" }
}

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

    /// Display precedence when one song carries several differently-badged versions:
    /// positive badges outrank negative ones. Mirrors the backend's `Song.badge` ordering.
    var displayPriority: Int {
        switch self {
        case .grail: 0
        case .best: 1
        case .special: 2
        case .wanted: 3
        case .worst: 4
        case .ai: 5
        }
    }

    /// Highest-precedence badge across *versions*, or nil when none carry one.
    static func mostSignificant(in versions: [SongVersion]) -> Badge? {
        versions
            .compactMap { $0.badge.flatMap(Badge.init(rawValue:)) }
            .min { $0.displayPriority < $1.displayPriority }
    }

    /// Canonical display label — the single source for every sheet that
    /// lists badges (description, legend, tracker stats).
    var label: String {
        switch self {
        case .best: "Best Of"
        case .special: "Special"
        case .worst: "Worst Of"
        case .grail: "Grail"
        case .wanted: "Wanted"
        case .ai: "AI"
        }
    }
}

nonisolated struct TrackerStats: Codable, Hashable, Sendable {
    // Links
    /// Every link the tracker counted, working or not — the denominator that
    /// turns "42 missing" into "42 of 1,203 missing".
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
    let ogFiles: Int?
    let stemBounces: Int?
    let full: Int?
    /// The "Total Full" wording, which already counts the OG files. Trackers use this
    /// or `full`, so a Carti-style sheet reports `full: 0` with everything in here.
    let totalFull: Int?
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
        case ogFiles = "og_files"
        case stemBounces = "stem_bounces"
        case totalFull = "total_full"
        case bestOf = "best_of"
        case worstOf = "worst_of"
    }
}

nonisolated struct Notice: Codable, Identifiable, Hashable, Sendable {
    let text: String
    let link: String?
    let kind: String?

    /// Composite identity: two notices with the same text but different kind
    /// or link must not collide in a ForEach (SwiftUI silently drops
    /// duplicate IDs, losing the second banner).
    var id: String { "\(kind ?? "info")::\(text)::\(link ?? "")" }

    var isAlert: Bool { kind == "alert" }
}

nonisolated struct TimelineEvent: Codable, Identifiable, Hashable, Sendable {
    let date: String
    let event: String

    var id: String { "\(date):\(event)" }
}

/// One entry of the backend /trackers discovery feed (ArtistGrid registry).
nonisolated struct DiscoveryArtist: Codable, Identifiable, Sendable {
    let name: String
    let url: String
    let credit: String?
    let best: Bool?
    let upToDate: Bool?
    /// The registry's link-health flag. Tri-state: "partially working" is neither true
    /// nor false, and known-dead links are worth flagging before the user opens it.
    let workingLinks: Bool?

    var id: String { url }

    enum CodingKeys: String, CodingKey {
        case name, url, credit, best
        case upToDate = "up_to_date"
        case workingLinks = "working_links"
    }
}
