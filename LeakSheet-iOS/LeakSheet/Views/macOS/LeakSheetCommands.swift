#if os(macOS)
import SwiftUI

/// Menu bar commands. Everything here drives a singleton, so no view state has
/// to be threaded up — see `MacUIState` for the two exceptions.
///
/// Deliberately no bare-`Space` Play/Pause binding: a menu shortcut with no
/// modifier fires even while a TextField has focus, which would make the
/// tracker URL field unusable.
struct LeakSheetCommands: Commands {
    /// Seconds moved by Skip Forward / Skip Back.
    private static let skipInterval: TimeInterval = 15

    @State private var player = PlayerViewModel.shared
    @State private var ui = MacUIState.shared
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        // The app has no documents; File ▸ New would open a stray window.
        CommandGroup(replacing: .newItem) {}

        CommandMenu("Playback") {
            Button(player.isPlaying ? "Pause" : "Play") {
                player.togglePlay()
            }
            .keyboardShortcut("p", modifiers: [.option, .command])
            .disabled(player.currentTrack == nil)

            Divider()

            Button("Next Track") { player.playNext() }
                .keyboardShortcut(.rightArrow, modifiers: .command)
                .disabled(player.currentTrack == nil)

            Button("Previous Track") { player.playPrevious() }
                .keyboardShortcut(.leftArrow, modifiers: .command)
                .disabled(player.currentTrack == nil)

            Divider()

            Button("Skip Forward") {
                player.seekTo(min(player.currentTime + Self.skipInterval, player.duration))
            }
            .keyboardShortcut(.rightArrow, modifiers: [.shift, .command])
            // Gated on duration too: currentTrack is set as soon as playback is
            // requested, before the asset reports its length. Without this,
            // pressing Skip Forward in that window computes min(15, 0) == 0
            // and seeks to the very start — Skip Forward rewinds.
            .disabled(player.currentTrack == nil || player.duration <= 0)

            Button("Skip Back") {
                player.seekTo(max(player.currentTime - Self.skipInterval, 0))
            }
            .keyboardShortcut(.leftArrow, modifiers: [.shift, .command])
            .disabled(player.currentTrack == nil || player.duration <= 0)
        }

        CommandMenu("Tracker") {
            Button("Refresh Tracker") { ui.refreshToken += 1 }
                .keyboardShortcut("r", modifiers: .command)

            Button("Paste Tracker URL") {
                guard let pasted = Pasteboard.string?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                    !pasted.isEmpty
                else { return }
                ui.pastedURL = pasted
            }
            .keyboardShortcut("v", modifiers: [.shift, .command])
        }

        CommandGroup(after: .toolbar) {
            Button(ui.showQueue ? "Hide Queue" : "Show Queue") {
                // The inspector this toggles lives only in the main window.
                // Bring it forward too, or toggling while the Now Playing
                // window is key changes state with no visible effect.
                ui.showQueue.toggle()
                openWindow(id: "main")
            }
            .keyboardShortcut("q", modifiers: [.option, .command])
        }
    }
}
#endif
