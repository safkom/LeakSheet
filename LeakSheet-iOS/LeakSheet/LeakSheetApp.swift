import SwiftUI
import AVFoundation
import OSLog

@main
struct LeakSheetApp: App {
    @Environment(\.scenePhase) private var scenePhase

    private static let log = Logger(subsystem: "si.safko.LeakSheet", category: "App")

    init() {
        configureAudioSession()
        // Settings writes the custom-server key through @AppStorage, which
        // notifies nothing — so the memoised base URL has to watch the store.
        MainActor.assumeIsolated { APIClient.startObservingBaseURL() }
    }

    var body: some Scene {
        #if os(macOS)
        // Window frames and sidebar state restore automatically on macOS —
        // `restorationBehavior` is the opt-out, so there's nothing to add here.
        //
        // `Window`, not `WindowGroup`: the commands raise this window by id
        // (⌘I and ⌥⌘Q drive an inspector only this window shows), and
        // `openWindow(id:)` on a WindowGroup OPENS ANOTHER COPY instead of
        // bringing the existing one forward — two identical main windows.
        // A Window scene is a singleton, and it also removes File ▸ New and
        // supplies its own Window-menu item for free.
        Window("LeakSheet", id: "main") {
            MacRootView()
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
                .environment(PlayerViewModel.shared)
                .environment(FavouritesManager.shared)
        }
        .defaultSize(width: 460, height: 700)
        .windowResizability(.contentMinSize)
        .keyboardShortcut("0", modifiers: [.command, .shift])

        // ⌘, — the Mac's one place for preferences. It used to be a sidebar row,
        // which is neither where a Mac user looks nor reachable by keyboard.
        Settings {
            SettingsView(embedded: true)
                .frame(width: 460, height: 520)
        }
        #else
        WindowGroup {
            ContentView()
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
