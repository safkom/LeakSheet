import AppIntents
import CoreSpotlight
import Observation

/// Where an intent leaves a tracker for the foreground UI to open, since an intent can run before any view exists.
@MainActor
@Observable
final class DeepLinkRouter {
    static let shared = DeepLinkRouter()
    var pending: PendingBrowse?
}

nonisolated struct IntentFailure: Error, CustomLocalizedStringResourceConvertible {
    let localizedStringResource: LocalizedStringResource
}

/// Also what Spotlight runs when a tracker result is tapped.
struct OpenTrackerIntent: OpenIntent {
    // Not a nonisolated type: a nonisolated @Parameter var doesn't compile, so only the statics are.
    nonisolated static let title: LocalizedStringResource = "Open Tracker"
    nonisolated static let description = IntentDescription("Opens a music tracker in LeakSheet.")
    nonisolated static let openAppWhenRun = true

    @Parameter(title: "Tracker")
    var target: TrackerEntity

    @MainActor
    func perform() async throws -> some IntentResult {
        DeepLinkRouter.shared.pending = PendingBrowse(url: target.id, name: target.name)
        return .result()
    }
}

struct PlayFavouriteIntent: AudioPlaybackIntent {
    nonisolated static let title: LocalizedStringResource = "Play Favourite Song"
    nonisolated static let description = IntentDescription("Plays a song from your favourites.")

    @Parameter(title: "Song")
    var song: FavouriteSongEntity

    @MainActor
    func perform() async throws -> some IntentResult {
        guard let entry = FavouritesManager.shared.entries.first(where: { $0.key == song.id }),
              let version = entry.toSongVersion, version.isStreamable
        else { throw IntentFailure(localizedStringResource: "That song can't be played right now.") }
        PlayerViewModel.shared.playTrack(
            version, artistName: entry.artistName, eraName: entry.eraName,
            artUrl: entry.eraArt ?? "", artistSlug: entry.artistSlug
        )
        return .result()
    }
}

nonisolated struct ShuffleFavouritesIntent: AudioPlaybackIntent {
    static let title: LocalizedStringResource = "Shuffle Favourites"
    static let description = IntentDescription("Plays your favourites shuffled, with similar leaks mixed in.")

    @MainActor
    func perform() async throws -> some IntentResult {
        let entries = FavouritesManager.shared.entries
        guard !entries.isEmpty else { throw IntentFailure(localizedStringResource: "You have no favourites yet.") }
        await PlayerViewModel.shared.playSmartShuffle(entries)
        return .result()
    }
}

nonisolated struct PlayPauseIntent: AudioPlaybackIntent {
    static let title: LocalizedStringResource = "Play or Pause"

    @MainActor
    func perform() async throws -> some IntentResult {
        PlayerViewModel.shared.togglePlay()
        return .result()
    }
}

nonisolated struct LeakSheetShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: OpenTrackerIntent(),
            phrases: ["Open \(\.$target) in \(.applicationName)", "Show \(\.$target) tracker in \(.applicationName)"],
            shortTitle: "Open Tracker", systemImageName: "music.note.list"
        )
        AppShortcut(
            intent: PlayFavouriteIntent(),
            phrases: ["Play \(\.$song) in \(.applicationName)"],
            shortTitle: "Play Favourite", systemImageName: "heart.fill"
        )
        AppShortcut(
            intent: ShuffleFavouritesIntent(),
            phrases: ["Shuffle my favourites in \(.applicationName)", "Play my leaks in \(.applicationName)"],
            shortTitle: "Shuffle Favourites", systemImageName: "shuffle"
        )
        AppShortcut(
            intent: PlayPauseIntent(),
            phrases: ["Play or pause \(.applicationName)"],
            shortTitle: "Play or Pause", systemImageName: "playpause.fill"
        )
    }
}

/// Keeps Spotlight's copy of trackers and favourites current. Songs inside trackers are not indexed:
/// thousands of rows per tracker, and a song needs its tracker loaded before it can play.
enum SpotlightIndexer {
    @MainActor
    static func refresh() async {
        let trackers = await TrackerCatalog.all()
        let songs = FavouritesManager.shared.entries.map(FavouriteSongEntity.init(entry:))
        let index = CSSearchableIndex.default()
        // Wiped first so removed favourites don't linger.
        try? await index.deleteAllSearchableItems()
        try? await index.indexAppEntities(trackers)
        try? await index.indexAppEntities(songs)
    }
}
