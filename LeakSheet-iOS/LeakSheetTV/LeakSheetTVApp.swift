import AVFoundation
import OSLog
import SwiftUI

@main
struct LeakSheetTVApp: App {
    @Environment(\.scenePhase) private var scenePhase

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
        // TVSettingsView writes the custom-server key through @AppStorage too,
        // so tvOS needs the same memo invalidation as iOS/macOS.
        MainActor.assumeIsolated { APIClient.startObservingBaseURL() }
    }

    var body: some Scene {
        WindowGroup {
            TVRootView()
                .environment(PlayerViewModel.shared)
                .environment(FavouritesManager.shared)
                .environment(RecentTrackersManager.shared)
        }
        // tvOS had no scenePhase observer at all, so handleBackgrounding()
        // never ran here: favourites and extracted era colours were lost
        // inside their debounce windows on every backgrounding, which is the
        // data loss the iOS side already fixed.
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                AudioEngine.shared.handleBackgrounding()
            }
        }
    }
}
