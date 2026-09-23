import AVFoundation
import OSLog
import SwiftUI

@main
struct LeakSheetTVApp: App {
    @Environment(\.scenePhase) private var scenePhase

    private static let log = Logger(subsystem: "si.safko.LeakSheet", category: "App")

    init() {
        // Category only, as on iOS: AudioEngine activates the session right before
        // playback so launch never interrupts another app's audio.
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [])
        } catch {
            Self.log.error("Failed to configure audio session: \(error.localizedDescription, privacy: .public)")
        }
    }

    var body: some Scene {
        WindowGroup {
            TVRootView()
                .environment(PlayerViewModel.shared)
                .environment(FavouritesManager.shared)
                .environment(RecentTrackersManager.shared)
        }
        // Flush debounced writes (favourites, era colours) on backgrounding, as on iOS.
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                AudioEngine.shared.handleBackgrounding()
            }
        }
    }
}
