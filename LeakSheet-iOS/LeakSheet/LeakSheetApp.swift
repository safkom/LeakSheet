import SwiftUI
import AVFoundation
import OSLog

@main
struct LeakSheetApp: App {
    @Environment(\.scenePhase) private var scenePhase
    /// Settings → Appearance. Applied to each scene's root; sheets and
    /// windows opened from it inherit the scheme.
    @AppStorage(AppAppearance.storageKey) private var appearance: AppAppearance = .platformDefault

    private static let log = Logger(subsystem: "si.safko.LeakSheet", category: "App")

    init() {
        configureAudioSession()
    }

    var body: some Scene {
        #if os(macOS)
        // Window frames and sidebar state restore automatically on macOS.
        // `Window`, not `WindowGroup`: see DECISIONS.md::LeakSheetApp.swift::window-scene
        Window("LeakSheet", id: "main") {
            MacRootView()
                .environment(PlayerViewModel.shared)
                .environment(FavouritesManager.shared)
                .environment(RecentTrackersManager.shared)
                .preferredColorScheme(appearance.colorScheme)
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
                .preferredColorScheme(appearance.colorScheme)
        }
        .defaultSize(width: 460, height: 700)
        .windowResizability(.contentMinSize)
        .keyboardShortcut("0", modifiers: [.command, .shift])

        // ⌘, — the Mac's one place for preferences.
        Settings {
            SettingsView(embedded: true)
                .frame(width: 460, height: 520)
                .preferredColorScheme(appearance.colorScheme)
        }
        #else
        WindowGroup {
            ContentView()
                .preferredColorScheme(appearance.colorScheme)
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
        // Only set the category here: activating at launch would interrupt other apps'
        // audio. AudioEngine activates the session right before playback.
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [])
        } catch {
            Self.log.error("Failed to configure audio session: \(error.localizedDescription, privacy: .public)")
        }
        #endif
    }
}
