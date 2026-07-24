import AVFoundation
import Foundation
import Observation

/// Global player view model — wraps AudioEngine for SwiftUI views.
@MainActor
@Observable
final class PlayerViewModel {
    static let shared = PlayerViewModel()

    private let engine = AudioEngine.shared

    var currentTrack: SongVersion? { engine.currentTrack }
    var artistName: String { engine.artistName }
    /// Canonical artist slug for the playing track — favourites key material.
    var artistSlug: String { engine.artistSlug }
    var eraName: String { engine.eraName }
    var artUrl: String { engine.artUrl }
    var isPlaying: Bool { engine.isPlaying }
    var currentTime: TimeInterval { engine.currentTime }
    var duration: TimeInterval { engine.duration }
    var loading: Bool { engine.loading }
    var error: String { engine.error }
    var queue: [QueueItem] { engine.queue }
    var originalQuality: Bool { engine.originalQuality }
    /// Live-captured stream format for the current track — File Info fallback.
    var streamFormat: StreamFormatInfo? { engine.streamFormat }
    var hasVideo: Bool { engine.hasVideo }
    var videoAspectRatio: Double? { engine.videoAspectRatio }
    var avPlayer: AVPlayer? { engine.currentPlayer }

    /// Shared seeking state — set `seeking = true` on drag start, false on commit.
    var seeking: Bool = false
    var seekValue: TimeInterval = 0
    /// Time value for display: shows seekValue while dragging, currentTime otherwise.
    var displayTime: TimeInterval { seeking ? seekValue : currentTime }

    /// Two-way projection for seek sliders: reads the display time, writes
    /// the scrub target. Lets views bind `$player.scrubPosition` instead of
    /// allocating a `Binding(get:set:)` closure on every body evaluation.
    var scrubPosition: TimeInterval {
        get { displayTime }
        set { seekValue = newValue }
    }

    private init() {}

    func playTrack(_ version: SongVersion, artistName: String = "", eraName: String = "", artUrl: String = "", artistSlug: String = "") {
        engine.playTrack(version, artistName: artistName, eraName: eraName, artUrl: artUrl, artistSlug: artistSlug)
    }

    func togglePlay() {
        engine.togglePlay()
    }

    func seekTo(_ time: TimeInterval) {
        engine.seekTo(time)
    }

    func stopTrack() {
        engine.stopTrack()
    }

    func addToQueue(_ version: SongVersion, artistName: String = "", eraName: String = "", artUrl: String = "", artistSlug: String = "") {
        engine.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: artUrl, artistSlug: artistSlug)
    }

    func removeFromQueue(at index: Int) {
        engine.removeFromQueue(at: index)
    }

    func clearQueue() {
        engine.clearQueue()
    }

    func moveInQueue(from: IndexSet, to: Int) {
        engine.moveInQueue(from: from, to: to)
    }

    func playFromQueue(at index: Int) {
        engine.playFromQueue(at: index)
    }

    func playNext() {
        engine.playNext()
    }

    func playPrevious() {
        engine.playPrevious()
    }

    func playOriginalQuality() {
        engine.playOriginalQuality()
    }

    func playCompressedStream() {
        engine.playCompressedStream()
    }

    /// Set era context and start playback in a single call so the two states
    /// can never be observed out of sync. Prefer this over calling
    /// `setEraSongs(...)` followed by `playTrack(...)`.
    func playInEra(_ version: SongVersion, eraName: String, artistName: String, artUrl: String, versions: [SongVersion], artistSlug: String? = nil) {
        engine.playInEra(version, eraName: eraName, artistName: artistName, artUrl: artUrl, versions: versions, artistSlug: artistSlug)
    }

    func setArtistEras(_ eras: [EraSongContext]) {
        engine.setArtistEras(eras)
    }

    /// Play a track as part of an ad-hoc ordered list (recents, search
    /// results, a song's versions) — auto-advance continues down the list.
    func playInList(_ items: [PlaybackListItem], startAt index: Int) {
        engine.playInList(items, startAt: index)
    }

    /// Format seconds as "m:ss".
    static func formatTime(_ seconds: TimeInterval) -> String {
        guard seconds.isFinite && seconds >= 0 else { return "0:00" }
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return "\(mins):\(String(format: "%02d", secs))"
    }
}
