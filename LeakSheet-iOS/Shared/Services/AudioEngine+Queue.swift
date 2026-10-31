import AVFoundation
import MediaPlayer
import Observation
import OSLog
import SwiftUI

extension AudioEngine {
    // MARK: - Queue

    func addToQueue(
        _ version: SongVersion,
        artistName: String = "",
        eraName: String = "",
        artUrl: String = "",
        artistSlug: String = "",
        playNext: Bool = false
    ) {
        logic.addToQueue(
            version,
            artistName: artistName,
            eraName: eraName,
            artUrl: artUrl,
            artistSlug: artistSlug,
            playNext: playNext
        )
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

    /// Atomic equivalent of `setEraSongs` followed by `playTrack`, kept as a
    /// single method so callers can't accidentally play a track without
    /// the era context that drives auto-advance.
    func playInEra(
        _ version: SongVersion,
        eraName: String,
        artistName: String,
        artUrl: String,
        versions: [SongVersion],
        artistSlug: String? = nil
    ) {
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

    func play(_ target: PlaybackQueueLogic.Target) {
        // Callers move the cursor before playing, so the list position is current here.
        syncQueue()
        playTrack(
            target.version,
            artistName: target.artistName,
            eraName: target.eraName,
            artUrl: target.artUrl,
            artistSlug: target.artistSlug,
            preservingQueueContext: true
        )
    }
}
