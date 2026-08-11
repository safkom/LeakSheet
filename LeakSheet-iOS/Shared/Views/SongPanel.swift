import SwiftUI

/// The tinted songs-panel treatment every song row sits in: era tint at 8%,
/// bottom corners rounded on the group's final row, 16pt screen inset.
///
/// It used to live as a private helper on `EraRowView`, so only the eras
/// branch got it. Search, Recents and the content tabs (Misc / Music Videos /
/// Released / Stems / …) rendered bare rows with nothing but horizontal
/// padding — no tint, no rounded tail, and no visual attachment to the era
/// card above them, which is why those pages looked like a different app.
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
