import SwiftUI

/// Control metrics that differ by input device: see
/// DECISIONS.md::Metrics.swift::input-device-metrics.
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
    /// Widest the reading column gets before it stops growing and centres, so a
    /// title doesn't sit ~1300pt from its own menu button.
    static let contentMaxWidth: CGFloat = 1000
    #else
    static let hitTarget: CGFloat = 44
    static let rowVerticalPadding: CGFloat = 8
    static let rowHorizontalPadding: CGFloat = 12
    static let chipHeight: CGFloat = 44
    static let contentMaxWidth: CGFloat = .infinity
    #endif
}
