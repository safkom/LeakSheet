import AVFoundation
import Foundation

// MARK: - Supporting Types

/// Format info captured from a live AVPlayerItem — the player-side fallback
/// for File Info when a stream host has no metadata API (e.g. krakenfiles).
nonisolated struct StreamFormatInfo: Equatable, Sendable {
    let codec: String?
    let sampleRateHz: Double?
    let channels: Int?
    let indicatedBitrateBps: Double?
    /// SongVersion.id this info was captured for — consumers match it
    /// against the version they display.
    let trackKey: String
}

struct QueueItem: Identifiable, Equatable, Sendable {
    let id: Int
    let version: SongVersion
    let artistName: String
    let eraName: String
    let artUrl: String
    /// Canonical API slug — favourites key material once this item plays.
    /// Optional call sites fall back to a slugified artist name.
    let artistSlug: String
}

struct EraSongContext: Sendable {
    let eraName: String
    let artistName: String
    let artUrl: String
    let versions: [SongVersion]
    /// Canonical API slug — optional so older call sites keep compiling;
    /// playback falls back to a slugified artist name when absent.
    var artistSlug: String? = nil
}

/// One entry of an ad-hoc playback list — each item carries its own era
/// metadata because such lists (recents, search results) span eras.
nonisolated struct PlaybackListItem: Equatable, Sendable {
    let version: SongVersion
    let artistName: String
    let eraName: String
    let artUrl: String
    /// Canonical API slug — optional so call sites without it keep compiling.
    var artistSlug: String? = nil
    /// Set on a smart-shuffle suggestion, so the queue can label it.
    var isInserted: Bool = false
}
