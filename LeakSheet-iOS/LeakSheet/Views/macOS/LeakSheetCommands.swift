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

    private var showingQueue: Bool { ui.showInspector && ui.inspectorTab == .queue }

    @State private var player = PlayerViewModel.shared
    @State private var ui = MacUIState.shared
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        // No CommandGroup(replacing: .newItem) and no hand-rolled Window-menu
        // items: both scenes are singleton `Window`s, so there is no File ▸ New
        // to remove and each already contributes its own Window-menu entry that
        // reopens it.

        CommandMenu("Playback") {
            Button(player.isPlaying ? "Pause" : "Play") {
                player.togglePlay()
            }
            .keyboardShortcut("p", modifiers: [.option, .command])
            .disabled(player.currentTrack == nil)

            Divider()

            // ⌥⌘←/→, not ⌘←/→: a menu key equivalent is matched before the
            // first responder sees the event, so binding the bare-⌘ arrows —
            // the system's move-to-start/end-of-line shortcuts — made them play
            // tracks instead of moving the caret in the tracker URL field.
            Button("Next Track") { player.playNext() }
                .keyboardShortcut(.rightArrow, modifiers: [.option, .command])
                .disabled(player.currentTrack == nil)

            Button("Previous Track") { player.playPrevious() }
                .keyboardShortcut(.leftArrow, modifiers: [.option, .command])
                .disabled(player.currentTrack == nil)

            Divider()

            Button("Skip Forward") {
                player.seekTo(min(player.currentTime + Self.skipInterval, player.duration))
            }
            .keyboardShortcut(.rightArrow, modifiers: [.shift, .option, .command])
            // Gated on duration too: currentTrack is set as soon as playback is
            // requested, before the asset reports its length. Without this,
            // pressing Skip Forward in that window computes min(15, 0) == 0
            // and seeks to the very start — Skip Forward rewinds.
            .disabled(player.currentTrack == nil || player.duration <= 0)

            Button("Skip Back") {
                player.seekTo(max(player.currentTime - Self.skipInterval, 0))
            }
            .keyboardShortcut(.leftArrow, modifiers: [.shift, .option, .command])
            .disabled(player.currentTrack == nil || player.duration <= 0)
        }

        CommandMenu("Tracker") {
            Button("Refresh Tracker") { ui.refreshToken += 1 }
                .keyboardShortcut("r", modifiers: .command)
                // Silently did nothing on every pane but a tracker.
                .disabled(ui.selectedSlug == nil)

            Button("Paste Tracker URL") {
                guard let pasted = Pasteboard.string?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                    !pasted.isEmpty
                else { return }
                ui.pastedURL = pasted
            }
            .keyboardShortcut("v", modifiers: [.shift, .command])
        }

        // Standard Find slot, so ⌘F lands where a Mac user expects it. The
        // artist screen owns the search field's focus, so this nudges a token
        // it observes rather than reaching into the view.
        CommandGroup(replacing: .textEditing) {
            Button("Find") {
                ui.focusSearchToken += 1
                openWindow(id: "main")
            }
            .keyboardShortcut("f", modifiers: .command)
        }

        CommandGroup(after: .toolbar) {
            // The inspector these drive lives only in the main window. Bring it
            // forward too, or toggling while the Now Playing window is key
            // changes state with no visible effect.
            Button("Song Details") {
                ui.inspectorTab = .details
                ui.showInspector = true
                openWindow(id: "main")
            }
            .keyboardShortcut("i", modifiers: .command)

            Button(showingQueue ? "Hide Queue" : "Show Queue") {
                if showingQueue {
                    ui.showInspector = false
                } else {
                    ui.inspectorTab = .queue
                    ui.showInspector = true
                }
                openWindow(id: "main")
            }
            .keyboardShortcut("q", modifiers: [.option, .command])
        }
    }
}
#endif
