import SwiftUI

/// The tinted songs-panel treatment every song row sits in: era tint at 8%, bottom
/// corners rounded on the group's final row, 16pt screen inset. Shared by every
/// list (eras, search, recents, content tabs) so they read as one app.
struct SongPanel: ViewModifier {
    /// Colors for the era this row belongs to. Nil until extraction lands, or
    /// when the row has no era (the tint then simply doesn't render).
    var displayColors: EraDisplayColors?
    /// Round the bottom corners — the last row under one era card.
    var isLast: Bool

    func body(content: Content) -> some View {
        content
            .frame(maxWidth: .infinity)
            .background(displayColors?.dominant.opacity(0.08) ?? Color.clear)
            .clipShape(
                UnevenRoundedRectangle(
                    bottomLeadingRadius: isLast ? 16 : 0,
                    bottomTrailingRadius: isLast ? 16 : 0
                )
            )
            .padding(.horizontal, 16)
    }
}

extension View {
    /// See `SongPanel`.
    func songPanel(_ displayColors: EraDisplayColors?, isLast: Bool = false) -> some View {
        modifier(SongPanel(displayColors: displayColors, isLast: isLast))
    }
}
