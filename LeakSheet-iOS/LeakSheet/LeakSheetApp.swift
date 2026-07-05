import SwiftUI
import AVFoundation

@main
struct LeakSheetApp: App {
    @Environment(\.scenePhase) private var scenePhase

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
            print("Failed to configure audio session: \(error)")
        }
    }
}
