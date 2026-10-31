#if os(macOS)
import SwiftUI

/// Menu bar commands. Everything here drives a singleton (see `MacUIState` for the
/// two exceptions). No bare-`Space` Play/Pause: a modifier-less menu shortcut fires
/// even while a TextField has focus.
struct LeakSheetCommands: Commands {
    /// Seconds moved by Skip Forward / Skip Back.
    private static let skipInterval: TimeInterval = 15

    private var showingQueue: Bool { uiState.showInspector && uiState.inspectorTab == .queue }
    private var showingDetails: Bool { uiState.showInspector && uiState.inspectorTab == .details }

    @State private var player = PlayerViewModel.shared
    @State private var uiState = MacUIState.shared
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        // No File ▸ New removal or hand-rolled Window-menu items: both scenes are
        // singleton `Window`s, which take care of both.

        CommandMenu("Playback") {
            Button(player.isPlaying ? "Pause" : "Play") {
                player.togglePlay()
            }
            .keyboardShortcut("p", modifiers: [.option, .command])
            .disabled(player.currentTrack == nil)

            Divider()

            // ⌥⌘←/→, not ⌘←/→: see DECISIONS.md::LeakSheetCommands.swift::arrow-modifiers
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
            // Gated on duration too: before the asset reports its length, min(15, 0) == 0
            // would make Skip Forward seek to the start.
            .disabled(player.currentTrack == nil || player.duration <= 0)

            Button("Skip Back") {
                player.seekTo(max(player.currentTime - Self.skipInterval, 0))
            }
            .keyboardShortcut(.leftArrow, modifiers: [.shift, .option, .command])
            .disabled(player.currentTrack == nil || player.duration <= 0)
        }

        CommandMenu("Go") {
            Button("Browse") { uiState.selection = .browse; openWindow(id: "main") }
                .keyboardShortcut("1", modifiers: .command)
            Button("Favourites") { uiState.selection = .favourites; openWindow(id: "main") }
                .keyboardShortcut("2", modifiers: .command)
        }

        // The app ships no help book, so the stock Help item would open nothing.
        CommandGroup(replacing: .help) {}

        CommandMenu("Tracker") {
            Button("Refresh Tracker") { uiState.refreshToken += 1 }
                .keyboardShortcut("r", modifiers: .command)
                // Only meaningful with a tracker selected.
                .disabled(uiState.selectedSlug == nil)

            Button("Paste Tracker URL") {
                guard let pasted = Pasteboard.string?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                    !pasted.isEmpty
                else { return }
                uiState.pastedURL = pasted
            }
            .keyboardShortcut("v", modifiers: [.shift, .command])
        }

        // Standard Find slot for ⌘F. The artist screen owns the search field's focus,
        // so this nudges a token it observes.
        CommandGroup(replacing: .textEditing) {
            Button("Find") {
                uiState.focusSearchToken += 1
                openWindow(id: "main")
            }
            .keyboardShortcut("f", modifiers: .command)
        }

        CommandGroup(after: .toolbar) {
            // The inspector lives only in the main window: bring it forward too, or toggling
            // while Now Playing is key has no visible effect.
            Button(showingDetails ? "Hide Song Details" : "Show Song Details") {
                if showingDetails {
                    uiState.showInspector = false
                } else {
                    uiState.inspectorTab = .details
                    uiState.showInspector = true
                }
                openWindow(id: "main")
            }
            .keyboardShortcut("i", modifiers: .command)

            Button(showingQueue ? "Hide Queue" : "Show Queue") {
                if showingQueue {
                    uiState.showInspector = false
                } else {
                    uiState.inspectorTab = .queue
                    uiState.showInspector = true
                }
                openWindow(id: "main")
            }
            .keyboardShortcut("q", modifiers: [.option, .command])
        }
    }
}
#endif
