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
        WindowGroup {
            ContentView()
                .preferredColorScheme(.dark)
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                AudioEngine.shared.handleBackgrounding()
            }
        }
    }

    private func configureAudioSession() {
        // Only set the category here. Activating the session at launch would
        // interrupt other apps' audio before the user plays anything —
        // AudioEngine activates the session right before playback instead.
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [])
        } catch {
            Self.log.error("Failed to configure audio session: \(error.localizedDescription, privacy: .public)")
        }
    }
}
