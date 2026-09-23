import SwiftUI

/// All display colors derived from an era's dominant color, computed once per
/// extraction (and appearance change) rather than per render.
nonisolated struct EraDisplayColors: Equatable, Sendable {
    /// Top-stop multiplier for the dark appearance: 0.55 for dim covers, stepped down
    /// for bright ones until white titles read, floored so a white cover keeps its tone.
    /// See DECISIONS.md::EraDisplayColors.swift::adaptive-dimming.
    private static func darkDimming(forLuminance luminance: Double) -> Double {
        var scale = 0.55
        // Linear luminance scales ~x^2.2 with the multiplier, so solving in
        // closed form is fiddlier than stepping; this runs once per era.
        while scale > 0.20 && luminance * pow(scale, 2.2) > 0.055 {
            scale -= 0.01
        }
        return scale
    }

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
        // Opaque gradient stops. `top`/`bottom` below carry opacity for the
        // render; the contrast decision uses the solid colours.
        let topSolid: Color
        let bottomSolid: Color
        if scheme == .dark {
            // Darken the cover colour toward the black background; the multiplier adapts to
            // the cover's brightness (see darkDimming).
            let scale = Self.darkDimming(forLuminance: dominant.relativeLuminance(in: scheme))
            topSolid = Color(red: r * scale, green: g * scale, blue: b * scale)
            let bottomScale = scale * (0.40 / 0.55)
            bottomSolid = Color(red: r * bottomScale, green: g * bottomScale, blue: b * bottomScale)
        } else {
            // Tint white WITH the cover instead: the dark multipliers would render every
            // card as a dark slab on a white page.
            topSolid = dominant.blended(with: .white, fraction: 0.68, in: scheme)
            bottomSolid = dominant.blended(with: .white, fraction: 0.82, in: scheme)
        }
        let top = topSolid.opacity(0.95)
        let bottom = bottomSolid.opacity(0.90)

        // Decide the title against the LIGHTER of the two stops, where light-on-light
        // fails (DECISIONS.md::EraDisplayColors.swift::adaptive-dimming).
        let effective = topSolid.relativeLuminance(in: scheme) >= bottomSolid.relativeLuminance(in: scheme)
            ? topSolid : bottomSolid
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
