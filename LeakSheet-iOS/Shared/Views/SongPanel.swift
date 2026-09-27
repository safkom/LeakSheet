import SwiftUI

/// The songs-panel treatment every song row sits in: an era-hued `lsCard` fill,
/// group corners rounded, 16pt screen inset. Shared by every list (eras, search,
/// recents, content tabs) so they read as one app.
struct SongPanel: ViewModifier {
    /// Colors for the era this row belongs to. Nil until extraction lands, or
    /// when the row has no era: the panel is then plain `lsCard`, same lightness.
    var displayColors: EraDisplayColors?
    /// Round the top corners — the first row of a group with no era card above it.
    var isFirst: Bool
    /// Round the bottom corners — the last row of the group.
    var isLast: Bool

    func body(content: Content) -> some View {
        content
            .frame(maxWidth: .infinity)
            .background(displayColors?.panel ?? Color.lsCard)
            .clipShape(
                UnevenRoundedRectangle(
                    topLeadingRadius: isFirst ? 16 : 0,
                    bottomLeadingRadius: isLast ? 16 : 0,
                    bottomTrailingRadius: isLast ? 16 : 0,
                    topTrailingRadius: isFirst ? 16 : 0
                )
            )
            .padding(.horizontal, 16)
    }
}

extension View {
    /// See `SongPanel`.
    func songPanel(_ displayColors: EraDisplayColors?, isFirst: Bool = false, isLast: Bool = false) -> some View {
        modifier(SongPanel(displayColors: displayColors, isFirst: isFirst, isLast: isLast))
    }
}
