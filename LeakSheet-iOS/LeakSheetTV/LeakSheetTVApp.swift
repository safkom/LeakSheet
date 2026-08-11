import AVFoundation
import OSLog
import SwiftUI

@main
struct LeakSheetTVApp: App {
    private static let log = Logger(subsystem: "eu.safko.LeakSheet", category: "App")

    init() {
        // tvOS has the full AVAudioSession API, so this matches iOS exactly.
        // Category only — AudioEngine activates the session right before
        // playback so we never interrupt another app's audio at launch.
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [])
        } catch {
            Self.log.error("Failed to configure audio session: \(error.localizedDescription, privacy: .public)")
        }
    }

    var body: some Scene {
        WindowGroup {
            TVRootView()
                .preferredColorScheme(.dark)
                .environment(PlayerViewModel.shared)
                .environment(FavouritesManager.shared)
                .environment(RecentTrackersManager.shared)
        }
    }
}
