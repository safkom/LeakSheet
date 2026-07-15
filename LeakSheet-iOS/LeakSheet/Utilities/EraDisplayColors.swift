import SwiftUI

/// All display colors derived from an era's dominant color, computed ONCE
/// when the color is extracted instead of per render. The derivations do
/// UIColor round-trips (`rgbComponents`, `ensureReadable`) that used to run
/// on every body evaluation of every era card and list header.
nonisolated struct EraDisplayColors: Equatable, Sendable {
    let dominant: Color
    /// Title text on the card's dimmed gradient.
    let title: Color
    /// Secondary text on the card.
    let body: Color
    /// Hairline card border.
    let border: Color
    /// Card background gradient endpoints.
    let gradientTop: Color
    let gradientBottom: Color
    /// Era-name group headers on the app background (recents/misc lists).
    let readableHeader: Color

    // The color helpers (rgbComponents, preferredText, ensureReadable) are
    // MainActor-isolated; derivation happens once per era on the main actor.
    @MainActor
    static func derive(from dominant: Color) -> EraDisplayColors {
        let (r, g, b) = dominant.rgbComponents
        let effective = Color(red: r * 0.48, green: g * 0.48, blue: b * 0.48)
        let title = Color.preferredText(on: effective)
        return EraDisplayColors(
            dominant: dominant,
            title: title,
            body: title.opacity(0.78),
            border: title.opacity(0.18),
            gradientTop: Color(red: r * 0.55, green: g * 0.55, blue: b * 0.55).opacity(0.95),
            gradientBottom: Color(red: r * 0.40, green: g * 0.40, blue: b * 0.40).opacity(0.90),
            readableHeader: dominant.ensureReadable(against: .lsBackground)
        )
    }
}
