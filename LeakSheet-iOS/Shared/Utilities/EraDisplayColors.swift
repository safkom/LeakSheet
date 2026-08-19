import SwiftUI

/// All display colors derived from an era's dominant color, computed ONCE when
/// the color is extracted — and again if the appearance changes — instead of
/// per render. The derivations do colour round-trips (`rgbComponents`,
/// `ensureReadable`) that used to run on every body evaluation of every era
/// card and list header.
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
    static func derive(from dominant: Color, in scheme: ColorScheme = .dark) -> EraDisplayColors {
        let (r, g, b) = dominant.rgbComponents(in: scheme)
        let effective: Color
        let top: Color
        let bottom: Color
        if scheme == .dark {
            // Darken the cover colour toward the black background.
            effective = Color(red: r * 0.48, green: g * 0.48, blue: b * 0.48)
            top = Color(red: r * 0.55, green: g * 0.55, blue: b * 0.55).opacity(0.95)
            bottom = Color(red: r * 0.40, green: g * 0.40, blue: b * 0.40).opacity(0.90)
        } else {
            // Tint white WITH the cover instead. Reusing the dark multipliers on
            // a white page renders every card as a dark slab; blending toward
            // white keeps the era's identity and reads as tinted paper.
            effective = dominant.blended(with: .white, fraction: 0.72, in: scheme)
            top = dominant.blended(with: .white, fraction: 0.68, in: scheme).opacity(0.95)
            bottom = dominant.blended(with: .white, fraction: 0.82, in: scheme).opacity(0.90)
        }
        let title = Color.preferredText(on: effective, in: scheme)
        return EraDisplayColors(
            dominant: dominant,
            title: title,
            body: title.opacity(0.78),
            border: title.opacity(0.18),
            gradientTop: top,
            gradientBottom: bottom,
            readableHeader: dominant.ensureReadable(against: .lsBackground, in: scheme)
        )
    }
}
