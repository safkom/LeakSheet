#if os(macOS)
import SwiftUI

/// The one piece of view state the menu bar has to reach. Everything else the
/// commands touch is already a singleton (`PlayerViewModel.shared`,
/// `AudioEngine.shared`), so this stays deliberately tiny.
@MainActor
@Observable
final class MacUIState {
    static let shared = MacUIState()

    /// Drives the queue inspector panel.
    var showQueue = false

    /// Bumped by ⌘R; the artist screen re-parses when it changes.
    var refreshToken = 0

    /// Set by ⇧⌘V so the Browse pane can pick up a pasted tracker URL.
    var pastedURL: String?

    private init() {}
}
#endif
