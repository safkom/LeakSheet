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

    /// Whether *version*, as listed under *era*, is the track now loaded.
    ///
    /// Name plus tag is not identity (placeholders, songs repeated across eras): the
    /// era narrows it to one list and the link set separates rows within it, compared
    /// raw because this runs in `body` per row. An empty era on either side (misc
    /// entries, bare Now Playing payloads) is not a mismatch.
    func isNowPlaying(_ version: SongVersion?, inEra era: String) -> Bool {
        guard let version, let current = currentTrack else { return false }
        guard current.name == version.name,
              current.versionTag == version.versionTag else { return false }
        if !eraName.isEmpty, !era.isEmpty, eraName != era { return false }
        return current.links == version.links
    }
    var artUrl: String { engine.artUrl }
    var isPlaying: Bool { engine.isPlaying }
    var currentTime: TimeInterval { engine.currentTime }
    var duration: TimeInterval { engine.duration }
    var loading: Bool { engine.loading }
    var error: String { engine.error }
    var queue: [QueueItem] { engine.queue }
    var upNext: [PlaybackListItem] { engine.upNext }
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

    func retryCurrent() {
        engine.retryCurrent()
    }

    func seekTo(_ time: TimeInterval) {
        engine.seekTo(time)
    }

    func addToQueue(_ version: SongVersion, artistName: String = "", eraName: String = "", artUrl: String = "", artistSlug: String = "", playNext: Bool = false) {
        engine.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: artUrl, artistSlug: artistSlug, playNext: playNext)
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

    // MARK: - Whole-era actions

    /// Plays the era's streamable versions in order, rolling into the next era at its end.
    func playEra(_ era: FilteredEra, artistName: String, artistSlug: String) {
        let versions = era.streamableVersions
        guard let first = versions.first else { return }
        playInEra(first, eraName: era.era.name, artistName: artistName, artUrl: era.era.artUrl ?? "",
                  versions: versions, artistSlug: artistSlug)
    }

    /// A list, not an era context: a shuffled era stops at its end instead of rolling on.
    func shuffleEra(_ era: FilteredEra, artistName: String, artistSlug: String) {
        let items = era.streamableVersions.shuffled().map {
            PlaybackListItem(version: $0, artistName: artistName, eraName: era.era.name,
                             artUrl: era.era.artUrl ?? "", artistSlug: artistSlug)
        }
        guard !items.isEmpty else { return }
        playInList(items, startAt: 0)
    }

    // MARK: - Radio

    /// Each song's best playable version of the era, shuffled, as a station that stops at its end.
    func playEraRadio(_ era: FilteredEra, artistName: String, artistSlug: String) {
        var rng = SystemRandomNumberGenerator()
        playInList(RadioBuilder.eraRadio(era: era, artistName: artistName, artistSlug: artistSlug, using: &rng),
                   startAt: 0)
    }

    func playCreditRadio(_ versions: [CreditProfile.Credited], artistName: String, artistSlug: String) {
        var rng = SystemRandomNumberGenerator()
        playInList(RadioBuilder.creditRadio(versions: versions, artistName: artistName, artistSlug: artistSlug,
                                            using: &rng), startAt: 0)
    }

    func playNewestLeaks(_ artist: Artist) {
        playInList(RadioBuilder.newestLeaks(artist: artist), startAt: 0)
    }

    /// Favourites shuffled, with suggestions from trackers already in the cache: a favourite
    /// whose tracker was never loaded gets none.
    func playSmartShuffle(_ entries: [FavouritesManager.FavouriteEntry]) async {
        let favourites: [PlaybackListItem] = entries.compactMap { entry in
            guard let version = entry.toSongVersion, version.isStreamable else { return nil }
            return PlaybackListItem(version: version, artistName: entry.artistName, eraName: entry.eraName,
                                    artUrl: entry.eraArt ?? "", artistSlug: entry.artistSlug)
        }
        var artists: [Artist] = []
        for url in Set(entries.compactMap(\.sourceUrl)) {
            if let artist = await CacheService.shared.getCachedArtist(for: url) { artists.append(artist) }
        }
        var rng = SystemRandomNumberGenerator()
        let station = RadioBuilder.smartShuffle(
            favourites: favourites,
            candidatesByEra: RadioBuilder.candidatesByEra(artists: artists),
            isHeard: { ListeningHistory.shared.isHeard($0.version, artistSlug: $0.artistSlug ?? "", eraName: $0.eraName) },
            using: &rng
        )
        playInList(station, startAt: 0)
    }

    // shortcut: the 200-item queue cap drops the rest of a bigger era silently; report the count if users hit it.
    func queueEra(_ era: FilteredEra, artistName: String, artistSlug: String) {
        for version in era.streamableVersions {
            addToQueue(version, artistName: artistName, eraName: era.era.name,
                       artUrl: era.era.artUrl ?? "", artistSlug: artistSlug)
        }
    }
}
