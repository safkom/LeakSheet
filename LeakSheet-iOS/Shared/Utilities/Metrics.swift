import SwiftUI

/// Control metrics that differ by input device. Touch platforms want the 44pt
/// HIG hit target; a Mac driven by a pointer wants roughly half that, and rows
/// sized for a finger waste about a third of a desktop window's vertical space.
///
/// Forked once here rather than at every call site — the alternative was ~15
/// `#if os(macOS)` branches scattered through shared leaf views.
nonisolated enum Metrics {
    #if os(macOS)
    /// Minimum square hit target for icon buttons.
    static let hitTarget: CGFloat = 24
    /// Vertical padding inside a list row.
    static let rowVerticalPadding: CGFloat = 5
    /// Horizontal padding inside a list row.
    static let rowHorizontalPadding: CGFloat = 10
    /// Minimum height of a filter chip.
    static let chipHeight: CGFloat = 24
    /// Widest the reading column gets before it stops growing and centres.
    /// Full-bleed rows on a 1400pt window put a song title ~1300pt from its
    /// own menu button.
    static let contentMaxWidth: CGFloat = 1000
    #else
    static let hitTarget: CGFloat = 44
    static let rowVerticalPadding: CGFloat = 8
    static let rowHorizontalPadding: CGFloat = 12
    static let chipHeight: CGFloat = 44
    static let contentMaxWidth: CGFloat = .infinity
    #endif
}
