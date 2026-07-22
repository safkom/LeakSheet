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

    private nonisolated static let log = Logger(subsystem: "eu.safko.LeakSheet", category: "Audio")

    // MARK: - State

    var currentTrack: SongVersion?
    var artistName = ""
    /// Canonical artist slug from the API — used as the favourites key so
    /// hearts toggled from the player match entries written from song rows.
    /// Falls back to a slugified name when a call site doesn't know it.
    private(set) var artistSlug = ""
    var eraName = ""
    var artUrl = ""
    var isPlaying = false
    var currentTime: TimeInterval = 0
    var duration: TimeInterval = 0
    var buffered: Double = 0
    var loading = false
    var error = ""
    var streamUrl = ""
    var volume: Float = 1.0
    var originalQuality = false
    /// Format info read from the live AVPlayerItem once playback is ready —
    /// the fallback source for File Info when a provider has no metadata API.
    private(set) var streamFormat: StreamFormatInfo?

    /// Playback-ordering decisions (queue, era rollover, ad-hoc lists) live
    /// in a pure value type so they are unit-testable; the engine executes
    /// its decisions against AVPlayer.
    private var logic = PlaybackQueueLogic()

    /// Cached from `logic.queue` after every mutation — reading `logic.queue`
    /// directly here would make every view that reads `queue` depend on the
    /// whole `PlaybackQueueLogic` struct (era/list cursors included), so era
    /// rollover or list bookkeeping unrelated to the visible queue would
    /// invalidate the queue sheet too.
    private(set) var queue: [QueueItem] = []

    // MARK: - Private

    private var player: AVPlayer?
    /// Read-only exposure for the Now Playing video surface — the layer
    /// binds to the same AVPlayer, so playback state/controls stay unified.
    var currentPlayer: AVPlayer? { player }
    /// True when the current item carries a video track (e.g. an .mp4
    /// behind an opaque pillows id). Set from the asset's track list in
    /// `captureStreamFormat` — the one signal that works for every host.
    private(set) var hasVideo = false
    /// width/height of the current video track (transform-corrected), so
    /// the Now Playing surface can size itself to the real picture instead
    /// of letterboxing inside the square artwork frame.
    private(set) var videoAspectRatio: Double?
    private var timeObserver: Any?
    private var observations: [NSKeyValueObservation] = []
    private var endOfTrackObserver: (any NSObjectProtocol)?
    private var interruptionObserver: (any NSObjectProtocol)?
    private var resumptionObserver: (any NSObjectProtocol)?
    private var loadingTimeoutTask: Task<Void, Never>?
    private var routeChangeObserver: (any NSObjectProtocol)?
    private var seekInFlight = false
    private var cachedArtworkUrl: String?
    private var cachedArtwork: MPMediaItemArtwork?

    private init() {
        volume = Self.loadVolume()
        setupRemoteCommands()
        setupInterruptionHandling()
    }
    // Note: NotificationCenter observers are intentionally not removed in a
    // deinit. AudioEngine is a process-lifetime singleton, and the
    // @MainActor-isolated, non-Sendable observer tokens cannot be safely
    // touched from a nonisolated deinit under Swift 6 isolation rules.

    // MARK: - Playback

    func playTrack(_ version: SongVersion?, artistName: String = "", eraName: String = "", artUrl: String = "", artistSlug: String = "") {
        currentTrack = version
        self.artistName = artistName
        self.artistSlug = artistSlug.isEmpty ? artistName.slugified : artistSlug
        self.eraName = eraName
        self.artUrl = artUrl
        currentTime = 0
        buffered = 0
        error = ""
        originalQuality = false
        streamFormat = nil
        hasVideo = false
        videoAspectRatio = nil
        duration = Self.parseDuration(version?.trackLength)

        guard let version, let link = version.streamableLink else {
            streamUrl = ""
            isPlaying = false
            loading = false
            return
        }

        guard let url = StreamResolver.streamURL(for: link) else {
            streamUrl = ""
            isPlaying = false
            loading = false
            error = "Stream host not supported"
            return
        }

        // Re-activate audio session before each playback attempt
        activateAudioSession()

        // If the user prefers original quality and one is available, start directly there
        // to avoid a double replaceCurrentItem (which re-runs KVO setup and causes an extra
        // PlayerRemoteXPC cycle + visible network teardown in the console).
        let prefersOriginal = UserDefaults.standard.bool(forKey: "leaksheet_streaming_mode")
        let originalURL = prefersOriginal ? StreamResolver.originalQualityURL(for: link) : nil
        let initialURL = originalURL ?? url

        streamUrl = initialURL.absoluteString
        originalQuality = originalURL != nil
        loading = true

        let asset = AVURLAsset(url: initialURL)
        let playerItem = AVPlayerItem(asset: asset)
        playerItem.preferredForwardBufferDuration = 10
        setupPlayer(with: playerItem)
        player?.play()
        updateNowPlayingInfo()
        startLoadingTimeout()

        // Early video hint from /metadata — the backend's stream-HEAD
        // fallback knows the mime before AVAsset finishes loading tracks,
        // so the Now Playing surface can show video without a late swap.
        // The asset's own track list (captureStreamFormat) stays
        // authoritative once loaded.
        let trackKey = version.id
        Task { [weak self] in
            guard let meta = try? await APIClient.shared.fetchMetadata(for: link),
                  meta.mediaKind == "video" else { return }
            guard let self, self.currentTrack?.id == trackKey else { return }
            self.hasVideo = true
        }
    }

    func togglePlay() {
        guard let player else {
            if let track = currentTrack, let link = track.streamableLink,
               let url = StreamResolver.streamURL(for: link) {
                activateAudioSession()
                let asset = AVURLAsset(url: url)
                let item = AVPlayerItem(asset: asset)
                item.preferredForwardBufferDuration = 10
                setupPlayer(with: item)
                player?.play()
                startLoadingTimeout()
            }
            return
        }

        if isPlaying {
            player.pause()
            isPlaying = false
        } else {
            player.play()
            // isPlaying set by timeControlStatus observer
        }
    }

    func seekTo(_ time: TimeInterval) {
        let cmTime = CMTime(seconds: time, preferredTimescale: 600)
        // Show the target position immediately, and suppress time-observer
        // writes until the seek lands — otherwise the observer briefly snaps
        // the slider back to the pre-seek position.
        seekInFlight = true
        currentTime = time
        player?.seek(to: cmTime, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.seekInFlight = false
            }
        }
    }

    func stopTrack() {
        streamFormat = nil
        loadingTimeoutTask?.cancel()
        loadingTimeoutTask = nil
        observations.forEach { $0.invalidate() }
        observations = []
        if let observer = timeObserver {
            player?.removeTimeObserver(observer)
            timeObserver = nil
        }
        player?.pause()
        // Cancel any in-flight asset loading so the underlying socket is torn down
        // immediately instead of leaking until it times out (surfaces as
        // `nw_read_request_report … Operation timed out` in the console).
        if let asset = player?.currentItem?.asset as? AVURLAsset {
            asset.cancelLoading()
        }
        player?.replaceCurrentItem(with: nil)
        currentTrack = nil
        isPlaying = false
        currentTime = 0
        duration = 0
        buffered = 0
        loading = false
        error = ""
        streamUrl = ""
        artUrl = ""
        artistSlug = ""
        cachedArtworkUrl = nil
        logic.clearContexts()
        clearNowPlayingInfo()
    }

    /// Refreshes the cached `queue` after a `logic` mutation that could have
    /// changed it. QueueItem is Equatable, so the @Observable setter skips
    /// the invalidation when the queue didn't actually change.
    private func syncQueue() {
        queue = logic.queue
    }

    func setVolume(_ vol: Float) {
        volume = max(0, min(1, vol))
        player?.volume = volume
        Self.saveVolume(volume)
    }

    /// Called when the app moves to background — pauses playback (background audio continues via AVSession).
    func handleBackgrounding() {
        // Audio session is already configured for background playback (.playback category).
        // This is a hook for any flush/cleanup needed (e.g. flushing cache).
        // Intentionally does not pause playback.
    }

    // MARK: - Original Quality

    func playOriginalQuality() {
        guard let track = currentTrack, let link = track.streamableLink else { return }
        guard let downloadURL = StreamResolver.originalQualityURL(for: link) else {
            error = "No original quality URL for this provider"
            return
        }

        let savedTime = currentTime
        let wasPlaying = isPlaying
        loading = true
        originalQuality = true
        error = ""
        // The new item is a different file for the same track — trackKey
        // alone can't tell captureStreamFormat this is stale.
        streamFormat = nil

        let asset = AVURLAsset(url: downloadURL)
        let item = AVPlayerItem(asset: asset)
        item.preferredForwardBufferDuration = 10
        setupPlayer(with: item, restoreTime: savedTime, autoPlay: wasPlaying)
        startLoadingTimeout()
    }

    func playCompressedStream() {
        guard let track = currentTrack, let link = track.streamableLink else { return }
        guard let url = StreamResolver.streamURL(for: link) else { return }

        let savedTime = currentTime
        let wasPlaying = isPlaying
        loading = true
        originalQuality = false
        streamUrl = url.absoluteString
        error = ""
        // The new item is a different file for the same track — trackKey
        // alone can't tell captureStreamFormat this is stale.
        streamFormat = nil

        let asset = AVURLAsset(url: url)
        let item = AVPlayerItem(asset: asset)
        item.preferredForwardBufferDuration = 10
        setupPlayer(with: item, restoreTime: savedTime, autoPlay: wasPlaying)
        startLoadingTimeout()
    }

    // MARK: - Queue

    func addToQueue(_ version: SongVersion, artistName: String = "", eraName: String = "", artUrl: String = "", artistSlug: String = "") {
        logic.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: artUrl, artistSlug: artistSlug)
        syncQueue()
    }

    func removeFromQueue(at index: Int) {
        logic.removeFromQueue(at: index)
        syncQueue()
    }

    func clearQueue() {
        logic.clearQueue()
        syncQueue()
    }

    func moveInQueue(from source: IndexSet, to destination: Int) {
        logic.moveInQueue(from: source, to: destination)
        syncQueue()
    }

    func playFromQueue(at index: Int) {
        guard let target = logic.playFromQueue(at: index) else { return }
        syncQueue()
        play(target)
    }

    func setEraSongs(eraName: String, artistName: String, artUrl: String, versions: [SongVersion], artistSlug: String? = nil) {
        logic.setEraSongs(EraSongContext(
            eraName: eraName,
            artistName: artistName,
            artUrl: artUrl,
            versions: versions,
            artistSlug: artistSlug
        ))
    }

    /// Atomic equivalent of `setEraSongs` followed by `playTrack`, kept as a
    /// single method so callers can't accidentally play a track without
    /// the era context that drives auto-advance.
    func playInEra(_ version: SongVersion, eraName: String, artistName: String, artUrl: String, versions: [SongVersion], artistSlug: String? = nil) {
        let context = EraSongContext(
            eraName: eraName,
            artistName: artistName,
            artUrl: artUrl,
            versions: versions,
            artistSlug: artistSlug
        )
        guard let target = logic.playInEra(version, context: context) else { return }
        play(target)
    }

    /// Start playback at `index` of an ad-hoc ordered list (recents, search
    /// results, a song's versions from the description sheet). Auto-advance
    /// continues down the list and stops at its end.
    func playInList(_ items: [PlaybackListItem], startAt index: Int) {
        guard let target = logic.playInList(items, startAt: index) else { return }
        play(target)
    }

    /// Register the ordered list of eras for the current artist so that, when the
    /// currently-playing era ends, playback automatically continues with the next era.
    func setArtistEras(_ eras: [EraSongContext]) {
        logic.setArtistEras(eras)
    }

    private func play(_ target: PlaybackQueueLogic.Target) {
        playTrack(
            target.version,
            artistName: target.artistName,
            eraName: target.eraName,
            artUrl: target.artUrl,
            artistSlug: target.artistSlug
        )
    }

    // MARK: - Private Setup

    private func setupPlayer(with item: AVPlayerItem, restoreTime: TimeInterval = 0, autoPlay: Bool = false) {
        // Cancel any pending loading timeout
        loadingTimeoutTask?.cancel()
        loadingTimeoutTask = nil

        // Invalidate all previous KVO observations
        observations.forEach { $0.invalidate() }
        observations = []
        if let observer = timeObserver {
            player?.removeTimeObserver(observer)
            timeObserver = nil
        }

        if player == nil {
            player = AVPlayer()
            player?.allowsExternalPlayback = false
            player?.automaticallyWaitsToMinimizeStalling = true
        }

        player?.replaceCurrentItem(with: item)
        player?.volume = volume
        player?.actionAtItemEnd = .none

        // Time observer (~10Hz for UI, now-playing updated less frequently)
        var tickCount = 0
        timeObserver = player?.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.1, preferredTimescale: 600),
            queue: .main
        ) { [weak self] time in
            MainActor.assumeIsolated {
                guard let self else { return }
                if !self.seekInFlight {
                    self.currentTime = time.seconds
                }
                // Update lock screen every ~3 seconds
                tickCount += 1
                if tickCount % 30 == 0 {
                    self.updateNowPlayingInfo()
                }
            }
        }

        // Status observer — restore seek position once ready
        // NOTE: KVO fires on arbitrary threads. Capture values before hopping to MainActor
        // to avoid Swift 6 actor-isolation violations (EXC_BREAKPOINT on background thread).
        observations.append(item.observe(\.status) { [weak self] item, _ in
            let status = item.status
            let dur = item.duration
            let errDesc = item.error?.localizedDescription
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch status {
                case .readyToPlay:
                    self.loading = false
                    self.loadingTimeoutTask?.cancel()
                    self.loadingTimeoutTask = nil
                    if dur.isValid && !dur.isIndefinite {
                        self.duration = dur.seconds
                    }
                    // Read format info from the (MainActor-held) current item
                    // rather than the KVO-captured one — AVPlayerItem is not
                    // Sendable, and a stale item is caught by the track guard.
                    if let currentItem = self.player?.currentItem {
                        Task { await self.captureStreamFormat(for: currentItem) }
                    }
                    // Restore position for quality-switch scenarios
                    if restoreTime > 0 {
                        self.seekTo(restoreTime)
                    }
                    if autoPlay {
                        self.player?.play()
                    }
                case .failed:
                    self.loading = false
                    self.isPlaying = false
                    self.loadingTimeoutTask?.cancel()
                    self.loadingTimeoutTask = nil
                    self.error = errDesc ?? "Playback failed"
                default:
                    break
                }
            }
        })

        // timeControlStatus observer — Apple's recommended way to track play/pause/waiting state
        if let p = player {
            observations.append(p.observe(\.timeControlStatus, changeHandler: { [weak self] player, _ in
                let status = player.timeControlStatus
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    switch status {
                    case .playing:
                        self.isPlaying = true
                        self.loading = false
                    case .paused:
                        self.isPlaying = false
                    case .waitingToPlayAtSpecifiedRate:
                        self.isPlaying = false
                        self.loading = true
                    @unknown default:
                        break
                    }
                    self.updateNowPlayingInfo()
                }
            }))
        }

        // Buffer observers — show loading when buffer runs dry
        observations.append(item.observe(\.isPlaybackBufferEmpty) { [weak self] item, _ in
            let empty = item.isPlaybackBufferEmpty
            Task { @MainActor [weak self] in
                guard let self else { return }
                if empty { self.loading = true }
            }
        })
        observations.append(item.observe(\.isPlaybackLikelyToKeepUp) { [weak self] item, _ in
            let keepUp = item.isPlaybackLikelyToKeepUp
            Task { @MainActor [weak self] in
                guard let self else { return }
                if keepUp { self.loading = false }
            }
        })

        // End-of-track notification
        if let observer = endOfTrackObserver {
            NotificationCenter.default.removeObserver(observer)
            endOfTrackObserver = nil
        }
        endOfTrackObserver = NotificationCenter.default.addObserver(
            forName: AVPlayerItem.didPlayToEndTimeNotification,
            object: item,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.isPlaying = false
                self.currentTime = 0
                // Settings → Playback → Autoplay next (default on).
                let defaults = UserDefaults.standard
                let autoplay = defaults.object(forKey: SettingsView.autoplayNextKey) == nil
                    || defaults.bool(forKey: SettingsView.autoplayNextKey)
                guard autoplay else { return }
                self.playNext()
            }
        }
    }

    // MARK: - Stream format capture

    /// Reads codec/sample-rate/channel info from the item's asset and the
    /// access log's indicated bitrate, then publishes it for the version
    /// that is still current. AVFoundation objects never leave the MainActor;
    /// only the value-type result is stored.
    private func captureStreamFormat(for item: AVPlayerItem) async {
        guard let trackKey = currentTrack?.id else { return }
        if streamFormat?.trackKey == trackKey { return }

        var codec: String?
        var sampleRate: Double?
        var channels: Int?
        var bitrateBps: Double?
        let loadedTracks = try? await item.asset.load(.tracks)
        if let loadedTracks, currentTrack?.id == trackKey {
            hasVideo = loadedTracks.contains { $0.mediaType == .video }
        }
        if let videoTrack = loadedTracks?.first(where: { $0.mediaType == .video }),
           let size = try? await videoTrack.load(.naturalSize),
           let transform = try? await videoTrack.load(.preferredTransform) {
            let transformed = size.applying(transform)
            let width = abs(transformed.width)
            let height = abs(transformed.height)
            if width > 0, height > 0, currentTrack?.id == trackKey {
                videoAspectRatio = width / height
            }
        }
        if let tracks = loadedTracks,
           let audioTrack = tracks.first(where: { $0.mediaType == .audio }) {
            if let descriptions = try? await audioTrack.load(.formatDescriptions),
               let description = descriptions.first {
                if let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(description)?.pointee {
                    sampleRate = asbd.mSampleRate > 0 ? asbd.mSampleRate : nil
                    channels = asbd.mChannelsPerFrame > 0 ? Int(asbd.mChannelsPerFrame) : nil
                }
                codec = Self.codecName(CMFormatDescriptionGetMediaSubType(description))
            }
            // estimatedDataRate reflects the container's own bitrate metadata
            // and is available for progressive downloads right away — unlike
            // accessLog's indicatedBitrate, which is an HLS-transfer metric
            // that's typically empty for the plain HTTP files every supported
            // host serves.
            if let rate = try? await audioTrack.load(.estimatedDataRate), rate > 0 {
                bitrateBps = Double(rate)
            }
        }
        if bitrateBps == nil {
            let indicated = item.accessLog()?.events.last?.indicatedBitrate ?? -1
            bitrateBps = indicated > 0 ? indicated : nil
        }

        // The track may have advanced while the asset loaded.
        guard currentTrack?.id == trackKey else { return }
        streamFormat = StreamFormatInfo(
            codec: codec,
            sampleRateHz: sampleRate,
            channels: channels,
            indicatedBitrateBps: bitrateBps,
            trackKey: trackKey
        )
    }

    // Internal (not private) so the unit tests can exercise the mapping.
    nonisolated static func codecName(_ fourCC: FourCharCode) -> String? {
        switch fourCC {
        case kAudioFormatMPEGLayer3: return "MP3"
        case kAudioFormatMPEG4AAC: return "AAC"
        case kAudioFormatMPEG4AAC_HE, kAudioFormatMPEG4AAC_HE_V2: return "AAC (HE)"
        case kAudioFormatFLAC: return "FLAC"
        case kAudioFormatAppleLossless: return "ALAC"
        case kAudioFormatLinearPCM: return "PCM"
        case kAudioFormatOpus: return "Opus"
        default:
            // Render the FourCC itself (e.g. "mp4a") when it's printable.
            let bytes = [
                UInt8((fourCC >> 24) & 0xFF), UInt8((fourCC >> 16) & 0xFF),
                UInt8((fourCC >> 8) & 0xFF), UInt8(fourCC & 0xFF),
            ]
            guard bytes.allSatisfy({ $0 >= 0x20 && $0 < 0x7F }) else { return nil }
            return String(decoding: bytes, as: UTF8.self).trimmingCharacters(in: .whitespaces).uppercased()
        }
    }

    // MARK: - Audio Session

    /// Re-setting the category on an already-active session is a slow,
    /// main-thread-blocking operation (SessionCore warns about it) — the
    /// category never changes after the first successful set, so do it once.
    private var audioCategoryConfigured = false

    private func activateAudioSession() {
        let session = AVAudioSession.sharedInstance()
        if !audioCategoryConfigured {
            do {
                try session.setCategory(.playback, mode: .default, options: [])
                audioCategoryConfigured = true
            } catch {
                Self.log.warning("Failed to set audio session category: \(error)")
            }
        }
        // iOS 27 asynchronous activation — synchronous setActive(true) on the
        // main thread triggers a UI-unresponsiveness runtime warning.
        session.activate(options: []) { activated, error in
            if let error {
                Self.log.warning("Audio session activation failed (activated=\(activated)): \(error)")
            }
        }
    }

    private func startLoadingTimeout() {
        loadingTimeoutTask?.cancel()
        loadingTimeoutTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(15))
            guard !Task.isCancelled, let self, self.loading else { return }
            self.loading = false
            self.isPlaying = false
            self.error = "Connection timed out — try again"
            self.player?.pause()
        }
    }

    func playNext() {
        // logic.next() may dequeue from the user queue (it wins over era/list
        // advance), so the cached queue can change here too.
        let advance = logic.next()
        syncQueue()
        switch advance {
        case .play(let target):
            play(target)
        case .restart:
            seekTo(0)
        case .stop:
            stopTrack()
        }
    }

    func playPrevious() {
        switch logic.previous(currentTime: currentTime) {
        case .play(let target):
            play(target)
        case .restart:
            seekTo(0)
        case .stop:
            stopTrack()
        }
    }

    // MARK: - Now Playing / Remote Commands

    // NOTE: Remote command handlers fire on arbitrary system threads.
    // Dispatch to MainActor via Task to avoid Swift 6 actor-isolation violations.
    private func setupRemoteCommands() {
        let commandCenter = MPRemoteCommandCenter.shared()

        commandCenter.playCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.togglePlay() }
            return .success
        }
        commandCenter.pauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.player?.pause() }
            return .success
        }
        commandCenter.nextTrackCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.playNext() }
            return .success
        }
        commandCenter.previousTrackCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.playPrevious() }
            return .success
        }
        commandCenter.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            let position = event.positionTime
            Task { @MainActor in self?.seekTo(position) }
            return .success
        }
        // Keep the seconds-skip commands disabled: when they're enabled the
        // lock screen shows ±skip buttons instead of previous/next track.
        // In-app skip buttons cover seconds-skipping (Self.skipInterval).
        commandCenter.skipForwardCommand.isEnabled = false
        commandCenter.skipBackwardCommand.isEnabled = false
    }

    private func setupInterruptionHandling() {
        // iOS 27 replaces AVAudioSession.interruptionNotification with a
        // deactivation notification (interruption began) and a resumption
        // recommendation notification (interruption ended + should resume).
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.didBecomeInactiveNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            // Extract info before crossing isolation boundary
            let context = notification.userInfo?[AVAudioSession.deactivationContextKey]
                as? AVAudioSession.DeactivationContext
            let systemDeactivated = context?.source == .system
            MainActor.assumeIsolated {
                guard let self, systemDeactivated else { return }
                self.isPlaying = false
            }
        }

        resumptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.resumptionRecommendationNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            let context = notification.userInfo?[AVAudioSession.resumptionContextKey]
                as? AVAudioSession.ResumptionContext
            let shouldResume = context?.recommendation == .shouldResume
            MainActor.assumeIsolated {
                guard let self, shouldResume else { return }
                AVAudioSession.sharedInstance().activate(options: []) { _, _ in }
                self.player?.play()
            }
        }

        // Pause when the active output route disappears (headphones unplugged,
        // Bluetooth device disconnected) — standard iOS media-app behavior.
        routeChangeObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            let rawReason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            let reason = rawReason.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
            MainActor.assumeIsolated {
                guard let self, reason == .oldDeviceUnavailable else { return }
                self.player?.pause()
                self.isPlaying = false
            }
        }
    }

    func updateNowPlayingInfo() {
        guard let track = currentTrack else {
            clearNowPlayingInfo()
            return
        }

        var info = [String: Any]()

        var title = track.name
        if let badge = Badge(rawValue: track.badge ?? "") {
            title = "\(badge.emoji) \(title)"
        }
        if let tag = track.versionTag {
            title += " [\(tag)]"
        }

        info[MPMediaItemPropertyTitle] = title
        info[MPMediaItemPropertyArtist] = artistName
        info[MPMediaItemPropertyAlbumTitle] = eraName
        info[MPMediaItemPropertyPlaybackDuration] = duration
        info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = currentTime
        info[MPNowPlayingInfoPropertyPlaybackRate] = isPlaying ? 1.0 : 0.0

        // Preserve cached artwork in the initial write so the lock screen never
        // flashes an empty thumbnail between info updates.
        if let cached = cachedArtwork, cachedArtworkUrl == artUrl {
            info[MPMediaItemPropertyArtwork] = cached
        }

        MPNowPlayingInfoCenter.default().nowPlayingInfo = info

        // Load artwork once per track (skip if already loaded for this artUrl)
        if !artUrl.isEmpty && cachedArtworkUrl != artUrl {
            let targetUrl = artUrl
            Task {
                await loadNowPlayingArtwork(targetUrl: targetUrl)
            }
        }
    }

    /// Builds an MPMediaItemArtwork from a UIImage.
    /// Must be nonisolated so the image-provider closure carries no actor isolation —
    /// MediaPlayer calls it from MPNowPlayingInfoCenter/accessQueue (background), and Swift 6
    /// runtime-checks that any @MainActor closure is invoked on the MainActor (EXC_BREAKPOINT).
    private nonisolated static func makeArtwork(from image: UIImage) -> MPMediaItemArtwork {
        MPMediaItemArtwork(boundsSize: image.size) { _ in image }
    }

    private func loadNowPlayingArtwork(targetUrl: String) async {
        guard !targetUrl.isEmpty else { return }
        var fullURL = targetUrl
        if fullURL.hasPrefix("//") { fullURL = "https:" + fullURL }
        guard let proxyURL = APIClient.shared.imageProxyURL(for: fullURL, width: 1600) else { return }

        guard let image = await ImageCache.shared.loadImage(from: proxyURL, maxPixelSize: 1600) else { return }
        // Guard against races: if the user advanced tracks while we were loading,
        // don't overwrite the newer track's artwork with the old one.
        guard artUrl == targetUrl else { return }

        let artwork = Self.makeArtwork(from: image)
        cachedArtworkUrl = targetUrl
        cachedArtwork = artwork

        var info = MPNowPlayingInfoCenter.default().nowPlayingInfo ?? [:]
        info[MPMediaItemPropertyArtwork] = artwork
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func clearNowPlayingInfo() {
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
    }

    // MARK: - Volume Persistence

    private static func loadVolume() -> Float {
        // Distinguish "never set" from "muted to 0" — UserDefaults.float returns
        // 0 for both, which previously reset a fully-muted user back to 1.0.
        guard UserDefaults.standard.object(forKey: "leaksheet_volume") != nil else { return 1.0 }
        return min(1, max(0, UserDefaults.standard.float(forKey: "leaksheet_volume")))
    }

    private static func saveVolume(_ v: Float) {
        UserDefaults.standard.set(v, forKey: "leaksheet_volume")
    }

    // MARK: - Duration Parsing

    static func parseDuration(_ str: String?) -> TimeInterval {
        guard let str, !str.isEmpty else { return 0 }
        let parts = str.split(separator: ":")
        let nums = parts.compactMap { Double($0) }
        guard nums.count == parts.count else { return 0 }
        switch nums.count {
        case 2: return nums[0] * 60 + nums[1]              // M:SS
        case 3: return nums[0] * 3600 + nums[1] * 60 + nums[2]  // H:MM:SS
        default: return 0
        }
    }
}

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
}
