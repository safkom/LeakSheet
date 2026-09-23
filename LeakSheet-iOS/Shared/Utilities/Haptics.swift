#if os(iOS)
import UIKit
#endif

/// Centralized haptic feedback; generators are created on demand. A no-op on macOS
/// and tvOS (no haptic engine), so callers stay platform-agnostic.
@MainActor
enum Haptics {
    static func light() {
        #if os(iOS)
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        #endif
    }
}
