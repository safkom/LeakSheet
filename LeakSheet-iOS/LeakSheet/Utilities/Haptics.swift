import UIKit

/// Centralized haptic feedback. Generators are created on-demand (iOS 17+ pattern — no retained instances needed).
@MainActor
enum Haptics {
    static func light() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }
}
