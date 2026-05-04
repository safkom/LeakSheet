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
    var eraName: String { engine.eraName }
    var artUrl: String { engine.artUrl }
    var isPlaying: Bool { engine.isPlaying }
    var currentTime: TimeInterval { engine.currentTime }
    var duration: TimeInterval { engine.duration }
    var buffered: Double { engine.buffered }
    var loading: Bool { engine.loading }
    var error: String { engine.error }
    var queue: [QueueItem] { engine.queue }
    var originalQuality: Bool { engine.originalQuality }

    /// Shared seeking state — set `seeking = true` on drag start, false on commit.
    var seeking: Bool = false
    var seekValue: TimeInterval = 0
    /// Time value for display: shows seekValue while dragging, currentTime otherwise.
    var displayTime: TimeInterval { seeking ? seekValue : currentTime }

    private init() {}

    func playTrack(_ version: SongVersion, artistName: String = "", eraName: String = "", artUrl: String = "") {
        engine.playTrack(version, artistName: artistName, eraName: eraName, artUrl: artUrl)
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

    func setVolume(_ v: Float) {
        engine.setVolume(v)
    }

    func addToQueue(_ version: SongVersion, artistName: String = "", eraName: String = "", artUrl: String = "") {
        engine.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: artUrl)
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

    func setEraSongs(eraName: String, artistName: String, artUrl: String, versions: [SongVersion]) {
        engine.setEraSongs(eraName: eraName, artistName: artistName, artUrl: artUrl, versions: versions)
    }

    func setArtistEras(_ eras: [EraSongContext]) {
        engine.setArtistEras(eras)
    }

    /// Format seconds as "m:ss".
    static func formatTime(_ seconds: TimeInterval) -> String {
        guard seconds.isFinite && seconds >= 0 else { return "0:00" }
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return "\(mins):\(String(format: "%02d", secs))"
    }
}
