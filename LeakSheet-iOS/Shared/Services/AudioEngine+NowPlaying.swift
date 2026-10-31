import AVFoundation
import MediaPlayer
import Observation
import OSLog
import SwiftUI

extension AudioEngine {
    // MARK: - Audio Session


    /// macOS has no AVAudioSession — CoreAudio handles routing and there is no
    /// interruption/deactivation model to observe. tvOS has the *full* iOS 27
    /// API, so this and `setupInterruptionHandling` fork on `os(macOS)`, not
    /// `os(iOS)`. See DECISIONS.md::AudioEngine.swift::audio-session-fork.
    func activateAudioSession() {
        #if os(macOS)
        // Nothing to activate; AVPlayer just plays.
        #else
        let session = AVAudioSession.sharedInstance()
        if !audioCategoryConfigured {
            do {
                try session.setCategory(.playback, mode: .default, options: [])
                audioCategoryConfigured = true
            } catch {
                Self.log.warning("Failed to set audio session category: \(error)")
            }
        }
        // iOS 27 asynchronous activation (a synchronous setActive on main warns). @Sendable:
        // the completion is unannotated and may run off-main (see setupRemoteCommands).
        session.activate(options: []) { @Sendable activated, error in
            if let error {
                Self.log.warning("Audio session activation failed (activated=\(activated)): \(error)")
            }
        }
        #endif
    }

    func isCurrentItem(_ id: ObjectIdentifier) -> Bool {
        player?.currentItem.map(ObjectIdentifier.init) == id
    }

    func startLoadingTimeout() {
        loadingTimeoutTask?.cancel()
        loadingTimeoutTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(15))
            guard !Task.isCancelled, let self, self.loading else { return }
            self.loading = false
            self.isPlaying = false
            self.awaitingHostCheck = true
            self.error = "Connection timed out — try again"
            Telemetry.report("Stream timed out", category: "Playback",
                             attributes: ["host": URL(string: self.currentTrack?.streamableLink ?? "")?.host ?? "-"])
            self.player?.pause()
            self.explainIfHostDown()
        }
    }

    /// After a failed load: when the backend reports this track's host down, say so
    /// instead of a generic error. Retry and the play button work as before.
    func explainIfHostDown() {
        let link = currentTrack?.streamableLink
        Task { [weak self] in
            await HostHealthStore.shared.refresh(force: true)
            guard let self else { return }
            self.awaitingHostCheck = false
            if let link, link == self.currentTrack?.streamableLink, !self.error.isEmpty,
               let host = HostHealthStore.shared.downHost(for: link) {
                // Setting `error` announces the host-down message (the didSet is live again).
                self.error = "\(host) is down right now. Try again in a minute."
            } else if !self.error.isEmpty {
                AccessibilityNotification.Announcement(self.error).post()
            }
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

    // Remote command handlers fire on arbitrary threads, so they hop to MainActor and
    // are explicitly @Sendable: unannotated, they'd infer MainActor and trap off-main.
    func setupRemoteCommands() {
        let commandCenter = MPRemoteCommandCenter.shared()

        commandCenter.playCommand.addTarget { @Sendable [weak self] _ in
            // resumePlayback, not togglePlay — a discrete Play must never pause.
            Task { @MainActor in self?.resumePlayback() }
            return .success
        }
        commandCenter.pauseCommand.addTarget { @Sendable [weak self] _ in
            Task { @MainActor in self?.player?.pause() }
            return .success
        }
        // The Mac's play/pause key and a wired headset's button send this, not play/pause.
        // Not on tvOS: the Siri Remote's button already toggles through onPlayPauseCommand.
        #if !os(tvOS)
        commandCenter.togglePlayPauseCommand.addTarget { @Sendable [weak self] _ in
            Task { @MainActor in self?.togglePlay() }
            return .success
        }
        #endif
        commandCenter.nextTrackCommand.addTarget { @Sendable [weak self] _ in
            Task { @MainActor in self?.playNext() }
            return .success
        }
        commandCenter.previousTrackCommand.addTarget { @Sendable [weak self] _ in
            Task { @MainActor in self?.playPrevious() }
            return .success
        }
        commandCenter.changePlaybackPositionCommand.addTarget { @Sendable [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            let position = event.positionTime
            Task { @MainActor in self?.seekTo(position) }
            return .success
        }
        // Seconds-skip commands stay disabled: enabled, the lock screen shows ±skip
        // buttons instead of previous/next track.
        commandCenter.skipForwardCommand.isEnabled = false
        commandCenter.skipBackwardCommand.isEnabled = false
    }

    func setupInterruptionHandling() {
        #if os(macOS)
        // macOS has no session interruption or route-change model to observe;
        // CoreAudio handles device changes below the AVPlayer.
        #else
        // iOS 27 replaces interruptionNotification with deactivation (began) and
        // resumption-recommendation (ended + should resume) notifications.
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
                self.resumeAfterInterruption = self.isPlaying
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
                // Only what the interruption stopped: a track the user had
                // paused must not start again when a call ends.
                guard let self, shouldResume, self.resumeAfterInterruption else { return }
                self.resumeAfterInterruption = false
                AVAudioSession.sharedInstance().activate(options: []) { @Sendable _, _ in }
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
        #endif
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
        #if os(macOS)
        // macOS routes media keys by this state; iOS infers it from the audio session.
        MPNowPlayingInfoCenter.default().playbackState = isPlaying ? .playing : .paused
        #endif

        // Load artwork once per track: `artworkAttemptedUrl` is set BEFORE the fetch, since
        // this runs every ~3s and a 404ing cover would otherwise be re-requested each time.
        if !artUrl.isEmpty, artworkAttemptedUrl != artUrl {
            let targetUrl = artUrl
            artworkAttemptedUrl = targetUrl
            Task {
                await loadNowPlayingArtwork(targetUrl: targetUrl)
            }
        }
    }

    /// Builds an MPMediaItemArtwork from a CGImage.
    /// Nonisolated: MediaPlayer calls the image provider on a background queue, where a
    /// @MainActor closure traps. `platformImage` is the app's last UIKit/AppKit boundary.
    private nonisolated static func makeArtwork(from image: CGImage) -> MPMediaItemArtwork {
        let size = CGSize(width: image.width, height: image.height)
        return MPMediaItemArtwork(boundsSize: size) { _ in platformImage(image) }
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

    func clearNowPlayingInfo() {
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
        #if os(macOS)
        MPNowPlayingInfoCenter.default().playbackState = .stopped
        #endif
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
