import Foundation

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
    /// Director credit, from "[dir. Name]" on music-video and visual rows.
    let director: String?
    let engineer: String?
    /// Performer from a dedicated Artist / Credited Artist column (collab-style
    /// trackers), distinct from `featuring`.
    let creditedArtists: String?
    let altTitles: [String]?
    let notes: String?
    let ogFilename: String?
    let ogFilenames: [String]?
    let samples: [String]?
    let trackLength: String?
    let fileDate: String?
    let leakDate: String?
    /// When a snippet/preview first surfaced; the only date a preview-only version has.
    let previewDate: String?
    let availableLength: String?
    let quality: String?
    /// Streaming Yes/No from a main-tab Streaming column.
    let streaming: Bool?
    let links: [String]?
    let dateOfRecording: String?
    let recordingLocation: String?
    let type: String?
    /// Labeled evidence links (Sources column, Travis-style trackers).
    /// Optional so payloads persisted before the field existed still decode.
    let sources: [SourceRef]?
    /// Fan star rating 1-5 extracted from the availability cell.
    let rating: Int?
    /// The source the user (or the recents list) picked to play; nil plays the
    /// first playable link. Local only: not in CodingKeys.
    private(set) var chosenLink: String? = nil

    /// Memberwise init with every field but `name` defaulted to nil — most
    /// callers (favourites, misc entries) only ever populate a handful.
    init(
        name: String,
        versionTag: String? = nil,
        badge: String? = nil,
        featuring: String? = nil,
        producers: String? = nil,
        collaboration: String? = nil,
        refs: String? = nil,
        director: String? = nil,
        engineer: String? = nil,
        creditedArtists: String? = nil,
        altTitles: [String]? = nil,
        notes: String? = nil,
        ogFilename: String? = nil,
        ogFilenames: [String]? = nil,
        samples: [String]? = nil,
        trackLength: String? = nil,
        fileDate: String? = nil,
        leakDate: String? = nil,
        previewDate: String? = nil,
        availableLength: String? = nil,
        quality: String? = nil,
        streaming: Bool? = nil,
        links: [String]? = nil,
        dateOfRecording: String? = nil,
        recordingLocation: String? = nil,
        type: String? = nil,
        sources: [SourceRef]? = nil,
        rating: Int? = nil
    ) {
        self.name = name
        self.versionTag = versionTag
        self.badge = badge
        self.featuring = featuring
        self.producers = producers
        self.collaboration = collaboration
        self.refs = refs
        self.director = director
        self.engineer = engineer
        self.creditedArtists = creditedArtists
        self.altTitles = altTitles
        self.notes = notes
        self.ogFilename = ogFilename
        self.ogFilenames = ogFilenames
        self.samples = samples
        self.trackLength = trackLength
        self.fileDate = fileDate
        self.leakDate = leakDate
        self.previewDate = previewDate
        self.availableLength = availableLength
        self.quality = quality
        self.streaming = streaming
        self.links = links
        self.dateOfRecording = dateOfRecording
        self.recordingLocation = recordingLocation
        self.type = type
        self.sources = sources
        self.rating = rating
    }

    /// Name + tag alone is not unique (untagged same-name versions are common);
    /// the file link tells them apart. A chosen source is a different track to the player.
    var id: String { "\(name)::\(versionTag ?? "")::\(chosenLink ?? links?.first ?? "")" }

    /// This version set to play `link` (nil: its first playable link).
    func playing(_ link: String?) -> SongVersion {
        var copy = self
        copy.chosenLink = link
        return copy
    }

    /// Every playable link, in sheet order.
    var streamableLinks: [String] {
        var seen = Set<String>()
        return (links ?? []).filter { link in
            StreamResolver.isStreamableURL(link)
                && !(URL(string: link).map { Self.pathHasNonAudioExtension($0.path) } ?? false)
                && seen.insert(link).inserted
        }
    }

    /// The link a recent leak most likely refers to. Snippet-type rows append each new
    /// leak after the older ones; a full file's row leads with the file itself
    /// (DECISIONS.md::Models.swift::recent-leak-link).
    var recentLeakLink: String? {
        guard (links?.count ?? 0) > 1 else { return nil }
        let links = streamableLinks
        guard links.count > 1 else { return nil }
        let availability = availableLength?.lowercased() ?? ""
        let appendsLeaks = ["snippet", "partial", "stem"].contains { availability.contains($0) }
        return appendsLeaks ? links.last : nil
    }

    /// File extensions that identify the linked file as NOT playable audio: such a
    /// version hides Play actions and opens the description sheet instead.
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
        if let chosenLink { return chosenLink }
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
        case name, badge, featuring, producers, collaboration, refs, director, engineer, notes, samples
        case quality, streaming, links, type, sources, rating
        case creditedArtists = "credited_artists"
        case versionTag = "version_tag"
        case altTitles = "alt_titles"
        case ogFilename = "og_filename"
        case ogFilenames = "og_filenames"
        case trackLength = "track_length"
        case fileDate = "file_date"
        case leakDate = "leak_date"
        case previewDate = "preview_date"
        case availableLength = "available_length"
        case dateOfRecording = "date_of_recording"
        case recordingLocation = "recording_location"
    }
}
