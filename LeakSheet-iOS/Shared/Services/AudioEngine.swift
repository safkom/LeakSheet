import AVFoundation
import MediaPlayer
import Observation
import OSLog
import SwiftUI

/// Singleton audio engine managing AVPlayer, queue, and system media controls.
@MainActor
@Observable
final class AudioEngine {
    static let shared = AudioEngine()

    /// UserDefaults key gating end-of-track auto-advance (default on). Declared on the
    /// reader so shared code doesn't depend on the per-platform Settings screen.
    static let autoplayNextKey = "leaksheet_autoplay_next"
    static let originalQualityKey = "leaksheet_streaming_mode"

    /// Unset reads as on: see DECISIONS.md::AudioEngine.swift::original-quality-default.
    static func prefersOriginalQuality(in defaults: UserDefaults = .standard) -> Bool {
        defaults.object(forKey: originalQualityKey) == nil || defaults.bool(forKey: originalQualityKey)
    }

    nonisolated static let log = Logger(subsystem: "si.safko.LeakSheet", category: "Audio")

    // MARK: - State

    var currentTrack: SongVersion?
    var artistName = ""
    /// Canonical artist slug from the API — the favourites key, so player hearts match
    /// song-row entries. Falls back to a slugified name when a call site doesn't know it.
    private(set) var artistSlug = ""
    var eraName = ""
    var artUrl = ""
    var isPlaying = false
    var currentTime: TimeInterval = 0
    var duration: TimeInterval = 0
    var loading = false
    var error = "" {
        didSet {
            // A failed load announces once, after the host check has picked its message.
            guard !error.isEmpty, error != oldValue, !awaitingHostCheck else { return }
            AccessibilityNotification.Announcement(error).post()
        }
    }
    var streamUrl = ""
    /// Format info read from the live AVPlayerItem once playback is ready —
    /// the fallback source for File Info when a provider has no metadata API.
    internal(set) var streamFormat: StreamFormatInfo?

    /// Playback-ordering decisions (queue, era rollover, ad-hoc lists) live
    /// in a pure value type so they are unit-testable; the engine executes
    /// its decisions against AVPlayer.
    var logic = PlaybackQueueLogic()

    /// Cached from `logic.queue` after every mutation, so views reading `queue` don't
    /// depend on the whole `PlaybackQueueLogic` (era/list cursors included).
    private(set) var queue: [QueueItem] = []
    /// The next list items after the cursor (the manual queue plays first and is not
    /// included). Refreshed with `queue`, so the Up Next section tracks the list.
    private(set) var upNext: [PlaybackListItem] = []

    // MARK: - Private
    /// Re-setting the category on an already-active session is a slow,
    /// main-thread-blocking operation (SessionCore warns about it) — the
    /// category never changes after the first successful set, so do it once.
    var audioCategoryConfigured = false

    var player: AVPlayer?
    /// Read-only exposure for the Now Playing video surface — the layer
    /// binds to the same AVPlayer, so playback state/controls stay unified.
    var currentPlayer: AVPlayer? { player }
    /// True when the current item carries a video track (e.g. an .mp4
    /// behind an opaque pillows id). Set from the asset's track list in
    /// `captureStreamFormat` — the one signal that works for every host.
    internal(set) var hasVideo = false
    /// width/height of the current video track (transform-corrected), so
    /// the Now Playing surface can size itself to the real picture instead
    /// of letterboxing inside the square artwork frame.
    internal(set) var videoAspectRatio: Double?
    var timeObserver: Any?
    var observations: [NSKeyValueObservation] = []
    var endOfTrackObserver: (any NSObjectProtocol)?
    var interruptionObserver: (any NSObjectProtocol)?
    var resumptionObserver: (any NSObjectProtocol)?
    /// Whether audio was playing when the system deactivated the session.
    @ObservationIgnored var resumeAfterInterruption = false
    @ObservationIgnored var awaitingHostCheck = false
    var loadingTimeoutTask: Task<Void, Never>?
    private var videoHintTask: Task<Void, Never>?
    var routeChangeObserver: (any NSObjectProtocol)?
    var seekInFlight = false
    /// Real playback time in the current load, summed from ticks; seeks don't add to it.
    @ObservationIgnored private var listenedSeconds: TimeInterval = 0
    @ObservationIgnored private var lastTickTime: TimeInterval?
    @ObservationIgnored private var recordedThisLoad = false
    /// Bumped per seek so a superseded seek's completion can't clear
    /// `seekInFlight` out from under the newer one.
    private var seekGeneration = 0
    var cachedArtworkUrl: String?
    var cachedArtwork: MPMediaItemArtwork?
    /// The artUrl we last STARTED a fetch for, successful or not: the retry guard
    /// (`cachedArtworkUrl` only advances on success).
    var artworkAttemptedUrl: String?

    private init() {
        setupRemoteCommands()
        setupInterruptionHandling()
    }
    // No deinit cleanup — see DECISIONS.md::AudioEngine.swift::no-deinit-cleanup

    // MARK: - Playback

    /// - Parameter preservingQueueContext: only the queue-aware entry points
    ///   (`playInEra` / `playInList` / `playFromQueue`) pass true. They set
    ///   their context and then route through here via `play(_:)`, so they
    ///   must not have it cleared out from under them.
    func playTrack(
        _ version: SongVersion?,
        artistName: String = "",
        eraName: String = "",
        artUrl: String = "",
        artistSlug: String = "",
        preservingQueueContext: Bool = false
    ) {
        // Ad-hoc playback must not inherit a leftover era/list cursor, or auto-advance
        // walks off into an unrelated song.
        if !preservingQueueContext {
            logic.clearContexts()
            syncQueue()
        }
        resetTrackState(version, artistName: artistName, eraName: eraName, artUrl: artUrl, artistSlug: artistSlug)
        guard let version, let link = version.streamableLink else {
            stopWithoutStream()
            return
        }
        guard let url = StreamResolver.streamURL(for: link) else {
            error = "Stream host not supported"
            Telemetry.report(
                "Unsupported stream host",
                category: "Playback",
                attributes: ["host": URL(string: link)?.host ?? "-"]
            )
            stopWithoutStream()
            return
        }

        // Re-activate audio session before each playback attempt
        activateAudioSession()

        // Start directly on original quality when preferred, avoiding a second
        // replaceCurrentItem (extra KVO setup and network teardown).
        let prefersOriginal = Self.prefersOriginalQuality()
        let originalURL = prefersOriginal ? StreamResolver.originalQualityURL(for: link) : nil
        let initialURL = originalURL ?? url

        streamUrl = initialURL.absoluteString
        loading = true

        let asset = AVURLAsset(url: initialURL)
        let playerItem = AVPlayerItem(asset: asset)
        playerItem.preferredForwardBufferDuration = 10
        setupPlayer(with: playerItem)
        player?.play()
        updateNowPlayingInfo()
        startLoadingTimeout()
        Task { await HostHealthStore.shared.refresh() }

        // Early video hint — see DECISIONS.md::AudioEngine.swift::early-video-hint
        // Held and cancelled on skip, so rapid skipping leaves no /metadata requests running.
        let trackKey = version.id
        videoHintTask?.cancel()
        videoHintTask = Task { [weak self] in
            guard let meta = try? await APIClient.shared.fetchMetadata(for: link),
                  meta.mediaKind == "video" else { return }
            guard let self, self.currentTrack?.id == trackKey else { return }
            self.hasVideo = true
        }
    }

    func togglePlay() {
        // A failed or missing item cannot resume: rebuild it, keeping the queue contexts.
        guard let player, let item = player.currentItem, item.status != .failed else {
            retryCurrent()
            return
        }

        // timeControlStatus, not isPlaying/loading: a stall reads isPlaying=false, loading=true
        // yet must pause, while a paused player with a stale loading flag must play.
        if player.timeControlStatus != .paused {
            player.pause()
            isPlaying = false
        } else {
            player.play()
            // isPlaying set by timeControlStatus observer
        }
    }

    /// Reload the current track from scratch without clearing the era/list/queue contexts.
    func retryCurrent() {
        guard let track = currentTrack else { return }
        playTrack(track, artistName: artistName, eraName: eraName, artUrl: artUrl,
                  artistSlug: artistSlug, preservingQueueContext: true)
    }

    /// Start playback, never stop it.
    ///
    /// `playCommand` is a discrete intent, not a toggle: CarPlay, Siri and a desynced
    /// lock screen send it unconditionally, so it must never pause.
    func resumePlayback() {
        guard !isPlaying else { return }
        guard let player, let item = player.currentItem, item.status != .failed else {
            retryCurrent()
            return
        }
        player.play()
    }

    func seekTo(_ time: TimeInterval) {
        // Without this guard the completion never runs and `seekInFlight` stays true
        // forever, freezing `currentTime` for every track (playTrack publishes state first).
        guard let player else { return }

        let cmTime = CMTime(seconds: time, preferredTimescale: 600)
        // Show the target position immediately and suppress time-observer writes until
        // the seek lands. A generation, not a bool: a superseded seek's completion still
        // runs (finished == false), and only the newest seek may clear the flag.
        seekGeneration &+= 1
        let generation = seekGeneration
        seekInFlight = true
        currentTime = time
        player.seek(to: cmTime, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, generation == self.seekGeneration else { return }
                self.seekInFlight = false
                // The lock screen otherwise extrapolates from the last
                // published elapsed time until the next 3-second tick.
                self.updateNowPlayingInfo()
            }
        }
    }

    /// Abandon any in-flight seek. Bumping the generation makes the outgoing
    /// seek's completion a no-op, so it cannot clear the flag for whatever is
    /// loaded next.
    func cancelPendingSeek() {
        seekGeneration &+= 1
        seekInFlight = false
    }

    func stopTrack() {
        streamFormat = nil
        cancelPendingSeek()
        loadingTimeoutTask?.cancel()
        loadingTimeoutTask = nil
        videoHintTask?.cancel()
        videoHintTask = nil
        observations.forEach { $0.invalidate() }
        observations = []
        if let observer = timeObserver {
            player?.removeTimeObserver(observer)
            timeObserver = nil
        }
        // Mirrors setupPlayer, which removes it before adding a new one.
        if let observer = endOfTrackObserver {
            NotificationCenter.default.removeObserver(observer)
            endOfTrackObserver = nil
        }
        player?.pause()
        // Cancel in-flight asset loading so the socket is torn down now instead of
        // leaking until it times out.
        if let asset = player?.currentItem?.asset as? AVURLAsset {
            asset.cancelLoading()
        }
        player?.replaceCurrentItem(with: nil)
        currentTrack = nil
        isPlaying = false
        currentTime = 0
        duration = 0
        loading = false
        error = ""
        streamUrl = ""
        artUrl = ""
        artistSlug = ""
        cachedArtworkUrl = nil
        cachedArtwork = nil
        artworkAttemptedUrl = nil
        // The AVPlayer outlives replaceCurrentItem(with: nil) and Now Playing branches on
        // hasVideo: on macOS a finished video would leave a black layer under "Not Playing".
        hasVideo = false
        videoAspectRatio = nil
        logic.clearContexts()
        syncQueue()
        clearNowPlayingInfo()
    }

    /// Refreshes the cached `queue` after a `logic` mutation that could have
    /// changed it. QueueItem is Equatable, so the @Observable setter skips
    /// the invalidation when the queue didn't actually change.
    func syncQueue() {
        queue = logic.queue
        upNext = logic.upcoming(limit: Self.upNextLimit)
    }

    private static let upNextLimit = 50

    /// Called when the app moves to background. Playback deliberately continues
    /// (the session is configured for it); this is where debounced writes are
    /// forced out before the process can be suspended or killed.
    func handleBackgrounding() {
        #if canImport(UIKit)
        // With nothing playing, the process can suspend before the writes finish. An
        // assertion still open at expiry gets the app killed, so expiry ends them all.
        let assertion = UIApplication.shared.beginBackgroundTask(withName: "Flush saved state") { [weak self] in
            self?.endFlushAssertions()
        }
        flushAssertions.insert(assertion)
        #endif
        Task {
            await FavouritesManager.shared.flush()
            await ListeningHistory.shared.flush()
            await EraColorExtractor.shared.flush()
            #if canImport(UIKit)
            if flushAssertions.remove(assertion) != nil { UIApplication.shared.endBackgroundTask(assertion) }
            #endif
        }
    }

    #if canImport(UIKit)
    private var flushAssertions: Set<UIBackgroundTaskIdentifier> = []

    private func endFlushAssertions() {
        flushAssertions.forEach(UIApplication.shared.endBackgroundTask)
        flushAssertions.removeAll()
    }
    #endif

    /// Adds the ticks since the last one, if they are one tick long: a seek jumps further.
    /// See DECISIONS.md::ListeningHistory.swift::listened-not-position.
    func accumulateListening(to position: TimeInterval) {
        defer { lastTickTime = position }
        guard isPlaying, let last = lastTickTime else { return }
        let delta = position - last
        guard delta > 0, delta < 1 else { return }
        listenedSeconds += delta
        guard !recordedThisLoad, let track = currentTrack,
              PlayThreshold.reached(listened: listenedSeconds, duration: duration)
        else { return }
        recordedThisLoad = true
        ListeningHistory.shared.record(
            track, artistSlug: artistSlug, artistName: artistName,
            eraName: eraName, eraArt: artUrl.isEmpty ? nil : artUrl
        )
    }

}

extension AudioEngine {
    private func resetTrackState(
        _ version: SongVersion?, artistName: String, eraName: String, artUrl: String, artistSlug: String
    ) {
        currentTrack = version
        self.artistName = artistName
        self.artistSlug = artistSlug.isEmpty ? artistName.slugified : artistSlug
        self.eraName = eraName
        self.artUrl = artUrl
        currentTime = 0
        error = ""
        streamFormat = nil
        hasVideo = false
        videoAspectRatio = nil
        duration = Self.parseDuration(version?.trackLength)
        listenedSeconds = 0
        lastTickTime = nil
        recordedThisLoad = false
    }

    /// A track with no playable stream must silence the OLD item, or it keeps playing (and
    /// driving the time observer and lock screen) under the new track's metadata.
    private func stopWithoutStream() {
        player?.pause()
        player?.replaceCurrentItem(with: nil)
        streamUrl = ""
        isPlaying = false
        loading = false
        updateNowPlayingInfo()
    }
}
