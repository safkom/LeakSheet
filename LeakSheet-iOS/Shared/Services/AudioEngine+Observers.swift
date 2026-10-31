import AVFoundation
import MediaPlayer
import Observation
import OSLog
import SwiftUI

extension AudioEngine {
    // MARK: - Private Setup

    func setupPlayer(with item: AVPlayerItem, restoreTime: TimeInterval = 0, autoPlay: Bool = false) {
        resetPlayerObservers()
        if player == nil {
            player = AVPlayer()
            player?.allowsExternalPlayback = false
            player?.automaticallyWaitsToMinimizeStalling = true
            player?.volume = volume
        }
        player?.replaceCurrentItem(with: item)
        player?.actionAtItemEnd = .none
        installTimeObserver()
        observeItem(item, restoreTime: restoreTime, autoPlay: autoPlay)
        observeTimeControlStatus()
        installEndOfTrackObserver(for: item)
    }

    private func resetPlayerObservers() {
        // Cancel any pending loading timeout
        loadingTimeoutTask?.cancel()
        loadingTimeoutTask = nil
        // A seek against the OUTGOING item is moot; its completion would otherwise keep
        // `seekInFlight` set and freeze the new track's scrubber.
        cancelPendingSeek()
        // Invalidate all previous KVO observations
        observations.forEach { $0.invalidate() }
        observations = []
        if let observer = timeObserver {
            player?.removeTimeObserver(observer)
            timeObserver = nil
        }
    }

    /// ~10Hz for the UI; the lock screen is updated every ~3 seconds.
    private func installTimeObserver() {
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
                self.accumulateListening(to: time.seconds)
                tickCount += 1
                if tickCount % 30 == 0 {
                    self.updateNowPlayingInfo()
                }
            }
        }
    }

    private func observeItem(_ item: AVPlayerItem, restoreTime: TimeInterval, autoPlay: Bool) {
        // Item callbacks hop to the main actor after the fact: one queued before a track change
        // must not act on the next track (error, seek, duration).
        let itemID = ObjectIdentifier(item)

        // Duration observer: `.status` fires once, often before a progressive (or FLAC/VBR)
        // body knows its duration. Captures only `dur`: AVPlayerItem is not Sendable.
        observations.append(item.observe(\.duration) { [weak self] item, _ in
            let dur = item.duration
            Task { @MainActor [weak self] in
                guard let self,
                      self.isCurrentItem(itemID),
                      dur.isValid,
                      !dur.isIndefinite,
                      dur.seconds > 0 else { return }
                self.duration = dur.seconds
            }
        })

        // Status observer — restore seek position once ready. KVO fires on arbitrary
        // threads: capture values before hopping to MainActor (Swift 6 isolation).
        observations.append(item.observe(\.status) { [weak self] item, _ in
            let status = item.status
            let dur = item.duration
            let errDesc = item.error?.localizedDescription
            Task { @MainActor [weak self] in
                guard let self, self.isCurrentItem(itemID) else { return }
                self.handleItemStatus(
                    status,
                    duration: dur,
                    error: errDesc,
                    restoreTime: restoreTime,
                    autoPlay: autoPlay
                )
            }
        })

        // Buffer observers — show loading when buffer runs dry
        observations.append(item.observe(\.isPlaybackBufferEmpty) { [weak self] item, _ in
            let empty = item.isPlaybackBufferEmpty
            Task { @MainActor [weak self] in
                guard let self, self.isCurrentItem(itemID) else { return }
                // The initial timeout is cancelled at .readyToPlay; re-arm it so a mid-track
                // stall on a dead stream surfaces an error.
                if empty {
                    self.loading = true
                    self.startLoadingTimeout()
                }
            }
        })
        observations.append(item.observe(\.isPlaybackLikelyToKeepUp) { [weak self] item, _ in
            let keepUp = item.isPlaybackLikelyToKeepUp
            Task { @MainActor [weak self] in
                guard let self, self.isCurrentItem(itemID) else { return }
                if keepUp {
                    self.loading = false
                    // Recovered before the re-armed stall timeout fired.
                    self.loadingTimeoutTask?.cancel()
                    self.loadingTimeoutTask = nil
                }
            }
        })
    }

    private func handleItemStatus(
        _ status: AVPlayerItem.Status, duration dur: CMTime, error errDesc: String?,
        restoreTime: TimeInterval, autoPlay: Bool
    ) {
        switch status {
        case .readyToPlay:
            loading = false
            loadingTimeoutTask?.cancel()
            loadingTimeoutTask = nil
            // `> 0`, as in the .duration observer: a definite ZERO here would destroy the
            // duration seeded from the tracker's length on a quality switch.
            if dur.isValid, !dur.isIndefinite, dur.seconds > 0 {
                duration = dur.seconds
            }
            // Read format info from the MainActor-held current item, not the KVO-captured one
            // (AVPlayerItem is not Sendable); a stale item is caught by the track and item guard.
            if let currentItem = player?.currentItem {
                Task { await self.captureStreamFormat(for: currentItem) }
            }
            // Restore position for quality-switch scenarios
            if restoreTime > 0 {
                seekTo(restoreTime)
            }
            if autoPlay {
                player?.play()
            }
        case .failed:
            loading = false
            isPlaying = false
            loadingTimeoutTask?.cancel()
            loadingTimeoutTask = nil
            awaitingHostCheck = true
            error = errDesc ?? "Playback failed"
            Telemetry.report("Playback failed: \(errDesc ?? "unknown")", category: "Playback",
                             attributes: ["host": URL(string: currentTrack?.streamableLink ?? "")?.host ?? "-"])
            explainIfHostDown()
        default:
            break
        }
    }

    /// Apple's recommended way to track play/pause/waiting state.
    private func observeTimeControlStatus() {
        guard let p = player else { return }
        observations.append(p.observe(\.timeControlStatus, changeHandler: { [weak self] player, _ in
            let status = player.timeControlStatus
            Task { @MainActor [weak self] in
                self?.handleTimeControlStatus(status)
            }
        }))
    }

    private func handleTimeControlStatus(_ status: AVPlayer.TimeControlStatus) {
        switch status {
        case .playing:
            isPlaying = true
            loading = false
            error = ""
        case .paused:
            isPlaying = false
            // A pause during a stall is the user's choice, not a timeout.
            loading = false
            loadingTimeoutTask?.cancel()
            loadingTimeoutTask = nil
        case .waitingToPlayAtSpecifiedRate:
            isPlaying = false
            loading = true
            // Arm the timeout, as the buffer-empty observer does: the initial one is cancelled
            // at .readyToPlay, and a stall that never empties the buffer needs one too.
            startLoadingTimeout()
        @unknown default:
            break
        }
        updateNowPlayingInfo()
    }

    private func installEndOfTrackObserver(for item: AVPlayerItem) {
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
                self?.handleEndOfTrack()
            }
        }
    }

    private func handleEndOfTrack() {
        isPlaying = false
        currentTime = 0
        // Settings → Playback → Autoplay next (default on).
        let defaults = UserDefaults.standard
        let autoplay = defaults.object(forKey: Self.autoplayNextKey) == nil
            || defaults.bool(forKey: Self.autoplayNextKey)
        guard autoplay else {
            // actionAtItemEnd is .none, so the item is parked at its end: AVPlayer won't restart
            // without a seek, and pausing first stops the seek from looping the track.
            player?.pause()
            player?.seek(to: .zero)
            return
        }
        playNext()
    }

    // MARK: - Stream format capture

    /// Reads codec/sample-rate/channel info from the item's asset and the
    /// access log's indicated bitrate, then publishes it for the version
    /// that is still current. AVFoundation objects never leave the MainActor;
    /// only the value-type result is stored.
    private struct AudioTrackFormat {
        var codec: String?
        var sampleRate: Double?
        var channels: Int?
        var bitrateBps: Double?
    }

    private static func aspectRatio(of videoTrack: AVAssetTrack) async -> CGFloat? {
        guard let size = try? await videoTrack.load(.naturalSize),
              let transform = try? await videoTrack.load(.preferredTransform) else { return nil }
        let transformed = size.applying(transform)
        let width = abs(transformed.width)
        let height = abs(transformed.height)
        return width > 0 && height > 0 ? width / height : nil
    }

    private static func audioFormat(of audioTrack: AVAssetTrack) async -> AudioTrackFormat {
        var format = AudioTrackFormat()
        if let descriptions = try? await audioTrack.load(.formatDescriptions),
           let description = descriptions.first {
            if let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(description)?.pointee {
                format.sampleRate = asbd.mSampleRate > 0 ? asbd.mSampleRate : nil
                format.channels = asbd.mChannelsPerFrame > 0 ? Int(asbd.mChannelsPerFrame) : nil
            }
            format.codec = codecName(CMFormatDescriptionGetMediaSubType(description))
        }
        // estimatedDataRate over accessLog — see DECISIONS.md::AudioEngine.swift::bitrate-source
        if let rate = try? await audioTrack.load(.estimatedDataRate), rate > 0 {
            format.bitrateBps = Double(rate)
        }
        return format
    }

    private func captureStreamFormat(for item: AVPlayerItem) async {
        guard let trackKey = currentTrack?.id else { return }
        if streamFormat?.trackKey == trackKey { return }

        let loadedTracks = try? await item.asset.load(.tracks)
        if let loadedTracks, currentTrack?.id == trackKey {
            hasVideo = loadedTracks.contains { $0.mediaType == .video }
        }
        if let videoTrack = loadedTracks?.first(where: { $0.mediaType == .video }),
           let ratio = await Self.aspectRatio(of: videoTrack), currentTrack?.id == trackKey {
            videoAspectRatio = ratio
        }
        var format = AudioTrackFormat()
        if let audioTrack = loadedTracks?.first(where: { $0.mediaType == .audio }) {
            format = await Self.audioFormat(of: audioTrack)
        }
        var bitrateBps = format.bitrateBps
        if bitrateBps == nil {
            // iOS 27 replaced the synchronous accessLog() with an async getter of the same
            // name (bridged from fetchAccessLogWithCompletionHandler:).
            let log = await item.accessLog
            let indicated = log?.events.last?.indicatedBitrate ?? -1
            bitrateBps = indicated > 0 ? indicated : nil
        }

        // The track may have advanced while the asset loaded, or a quality switch replaced
        // the item: same track id, other file, and its own capture would then stop at the
        // trackKey check above and leave this one's format showing.
        guard currentTrack?.id == trackKey, player?.currentItem === item else { return }
        streamFormat = StreamFormatInfo(
            codec: format.codec,
            sampleRateHz: format.sampleRate,
            channels: format.channels,
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
                UInt8((fourCC >> 8) & 0xFF), UInt8(fourCC & 0xFF)
            ]
            guard bytes.allSatisfy({ $0 >= 0x20 && $0 < 0x7F }) else { return nil }
            return String(decoding: bytes, as: UTF8.self).trimmingCharacters(in: .whitespaces).uppercased()
        }
    }
}
