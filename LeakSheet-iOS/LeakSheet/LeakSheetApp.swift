import SwiftUI
import AVFoundation
import OSLog

@main
struct LeakSheetApp: App {
    @Environment(\.scenePhase) private var scenePhase

    private static let log = Logger(subsystem: "eu.safko.LeakSheet", category: "App")

    init() {
        configureAudioSession()
    }

    var body: some Scene {
        #if os(macOS)
        // Window frames and sidebar state restore automatically on macOS —
        // `restorationBehavior` is the opt-out, so there's nothing to add here.
        WindowGroup {
            MacRootView()
                .preferredColorScheme(.dark)
                .environment(PlayerViewModel.shared)
                .environment(FavouritesManager.shared)
                .environment(RecentTrackersManager.shared)
        }
        .defaultSize(width: 1180, height: 800)
        .windowResizability(.contentMinSize)
        .commands { LeakSheetCommands() }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                AudioEngine.shared.handleBackgrounding()
            }
        }

        Window("Now Playing", id: "now-playing") {
            NowPlayingView()
                .preferredColorScheme(.dark)
                .environment(PlayerViewModel.shared)
                .environment(FavouritesManager.shared)
        }
        .defaultSize(width: 440, height: 660)
        .windowResizability(.contentMinSize)
        .keyboardShortcut("0", modifiers: [.command, .shift])
        #else
        WindowGroup {
            ContentView()
                .preferredColorScheme(.dark)
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                AudioEngine.shared.handleBackgrounding()
            }
        }
        #endif
    }

    private func configureAudioSession() {
        #if os(macOS)
        // macOS has no AVAudioSession.
        #else
        // Only set the category here. Activating the session at launch would
        // interrupt other apps' audio before the user plays anything —
        // AudioEngine activates the session right before playback instead.
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [])
        } catch {
            Self.log.error("Failed to configure audio session: \(error.localizedDescription, privacy: .public)")
        }
        #endif
    }
}
