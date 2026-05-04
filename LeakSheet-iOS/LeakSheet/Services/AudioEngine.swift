import AVFoundation
import MediaPlayer
import Observation
import SwiftUI

/// Singleton audio engine managing AVPlayer, queue, and system media controls.
@MainActor
@Observable
final class AudioEngine {
    static let shared = AudioEngine()

    // MARK: - State

    var currentTrack: SongVersion?
    var artistName = ""
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
    var queue: [QueueItem] = []
    var originalQuality = false

    private(set) var eraSongs: EraSongContext?
    /// Optional list of all eras in the current artist, in display order,
    /// used to auto-continue playback past the end of the current era.
    private(set) var artistEras: [EraSongContext] = []

    // MARK: - Private

    private var player: AVPlayer?
    private var timeObserver: Any?
    private var observations: [NSKeyValueObservation] = []
    private var endOfTrackObserver: (any NSObjectProtocol)?
    private var interruptionObserver: (any NSObjectProtocol)?
    private var loadingTimeoutTask: Task<Void, Never>?
    private var queueIdCounter = 0
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

    func playTrack(_ version: SongVersion?, artistName: String = "", eraName: String = "", artUrl: String = "") {
        currentTrack = version
        self.artistName = artistName
        self.eraName = eraName
        self.artUrl = artUrl
        currentTime = 0
        buffered = 0
        error = ""
        originalQuality = false
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
        player?.seek(to: cmTime, toleranceBefore: .zero, toleranceAfter: .zero)
        currentTime = time
    }

    func stopTrack() {
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
        cachedArtworkUrl = nil
        eraSongs = nil
        clearNowPlayingInfo()
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

        let asset = AVURLAsset(url: url)
        let item = AVPlayerItem(asset: asset)
        item.preferredForwardBufferDuration = 10
        setupPlayer(with: item, restoreTime: savedTime, autoPlay: wasPlaying)
        startLoadingTimeout()
    }

    // MARK: - Queue

    func addToQueue(_ version: SongVersion, artistName: String = "", eraName: String = "", artUrl: String = "") {
        guard queue.count < 200 else { return }
        queueIdCounter += 1
        queue.append(QueueItem(
            id: queueIdCounter,
            version: version,
            artistName: artistName,
            eraName: eraName,
            artUrl: artUrl
        ))
    }

    func removeFromQueue(at index: Int) {
        guard queue.indices.contains(index) else { return }
        queue.remove(at: index)
    }

    func clearQueue() {
        queue.removeAll()
    }

    func moveInQueue(from source: IndexSet, to destination: Int) {
        queue.move(fromOffsets: source, toOffset: destination)
    }

    func playFromQueue(at index: Int) {
        guard queue.indices.contains(index) else { return }
        let item = queue.remove(at: index)
        playTrack(item.version, artistName: item.artistName, eraName: item.eraName, artUrl: item.artUrl)
    }

    func setEraSongs(eraName: String, artistName: String, artUrl: String, versions: [SongVersion]) {
        eraSongs = EraSongContext(
            eraName: eraName,
            artistName: artistName,
            artUrl: artUrl,
            versions: versions
        )
    }

    /// Register the ordered list of eras for the current artist so that, when the
    /// currently-playing era ends, playback automatically continues with the next era.
    func setArtistEras(_ eras: [EraSongContext]) {
        artistEras = eras
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
                self.currentTime = time.seconds
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
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.isPlaying = false
                self.currentTime = 0
                self.playNext()
            }
        }
    }

    // MARK: - Audio Session

    private func activateAudioSession() {
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            // Best-effort — playback may still work with default session
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
        // Try queue first
        if !queue.isEmpty {
            playFromQueue(at: 0)
            return
        }

        // Try next song in era
        guard let context = eraSongs, let current = currentTrack else {
            stopTrack()
            return
        }

        if let idx = context.versions.firstIndex(where: { $0.name == current.name && $0.versionTag == current.versionTag }),
           idx + 1 < context.versions.count {
            let next = context.versions[idx + 1]
            playTrack(next, artistName: context.artistName, eraName: context.eraName, artUrl: context.artUrl)
            return
        }

        // End of current era — roll over to the next era with streamable versions.
        if let nextEra = nextEraAfter(context), let first = nextEra.versions.first {
            eraSongs = nextEra
            playTrack(first, artistName: nextEra.artistName, eraName: nextEra.eraName, artUrl: nextEra.artUrl)
            return
        }

        stopTrack()
    }

    private func nextEraAfter(_ current: EraSongContext) -> EraSongContext? {
        guard let idx = artistEras.firstIndex(where: { $0.eraName == current.eraName && $0.artistName == current.artistName }) else {
            return nil
        }
        for candidate in artistEras.dropFirst(idx + 1) where !candidate.versions.isEmpty {
            return candidate
        }
        return nil
    }

    func playPrevious() {
        // If more than 3 seconds in, restart current track
        if currentTime > 3 {
            seekTo(0)
            return
        }

        // Try previous song in era context
        guard let context = eraSongs, let current = currentTrack else {
            seekTo(0)
            return
        }

        if let idx = context.versions.firstIndex(where: { $0.name == current.name && $0.versionTag == current.versionTag }),
           idx > 0 {
            let prev = context.versions[idx - 1]
            playTrack(prev, artistName: context.artistName, eraName: context.eraName, artUrl: context.artUrl)
        } else {
            seekTo(0)
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
        commandCenter.skipForwardCommand.preferredIntervals = [10]
        commandCenter.skipForwardCommand.addTarget { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.seekTo(self.currentTime + 10)
            }
            return .success
        }
        commandCenter.skipBackwardCommand.preferredIntervals = [10]
        commandCenter.skipBackwardCommand.addTarget { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.seekTo(max(0, self.currentTime - 10))
            }
            return .success
        }
    }

    private func setupInterruptionHandling() {
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            // Extract info before crossing isolation boundary
            let userInfo = notification.userInfo
            let typeValue = userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let optionsValue = userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt
            MainActor.assumeIsolated {
                guard let self,
                      let typeValue,
                      let type = AVAudioSession.InterruptionType(rawValue: typeValue) else { return }

                switch type {
                case .began:
                    self.isPlaying = false
                case .ended:
                    guard let optionsValue else { return }
                    let options = AVAudioSession.InterruptionOptions(rawValue: optionsValue)
                    if options.contains(.shouldResume) {
                        try? AVAudioSession.sharedInstance().setActive(true)
                        self.player?.play()
                    }
                @unknown default:
                    break
                }
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
        guard let proxyURL = APIClient.shared.imageProxyURL(for: fullURL) else { return }

        guard let image = await ImageCache.shared.loadImage(from: proxyURL) else { return }
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
        let v = UserDefaults.standard.float(forKey: "leaksheet_volume")
        return v > 0 ? min(1, v) : 1.0
    }

    private static func saveVolume(_ v: Float) {
        UserDefaults.standard.set(v, forKey: "leaksheet_volume")
    }

    // MARK: - Duration Parsing

    static func parseDuration(_ str: String?) -> TimeInterval {
        guard let str, !str.isEmpty else { return 0 }
        let parts = str.split(separator: ":")
        guard parts.count == 2,
              let mins = Double(parts[0]),
              let secs = Double(parts[1]) else { return 0 }
        return mins * 60 + secs
    }
}

// MARK: - Supporting Types

struct QueueItem: Identifiable, Sendable {
    let id: Int
    let version: SongVersion
    let artistName: String
    let eraName: String
    let artUrl: String
}

struct EraSongContext: Sendable {
    let eraName: String
    let artistName: String
    let artUrl: String
    let versions: [SongVersion]
}
