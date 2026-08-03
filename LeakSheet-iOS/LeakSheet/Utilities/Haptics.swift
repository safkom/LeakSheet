#if os(iOS)
import UIKit
#endif

/// Centralized haptic feedback. Generators are created on-demand (iOS 17+ pattern — no retained instances needed).
/// No-op on macOS and tvOS, neither of which has a haptic engine — this file is
/// the only call site of the API, so all 17 callers stay platform-agnostic.
@MainActor
enum Haptics {
    static func light() {
        #if os(iOS)
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        #endif
    }
}
