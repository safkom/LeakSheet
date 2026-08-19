import SwiftUI

/// All display colors derived from an era's dominant color, computed ONCE when
/// the color is extracted — and again if the appearance changes — instead of
/// per render. The derivations do colour round-trips (`rgbComponents`,
/// `ensureReadable`) that used to run on every body evaluation of every era
/// card and list header.
nonisolated struct EraDisplayColors: Equatable, Sendable {
    /// Top-stop multiplier for the dark appearance: the shipped 0.55 for covers
    /// that are already dim, stepped down for bright ones until the card is dark
    /// enough to title in white. Floored so a white cover still keeps a hint of
    /// its own tone rather than collapsing to black.
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
            // Darken the cover colour toward the black background.
            //
            // The multiplier adapts to how bright the cover is. Fixed 0.55/0.40
            // was tuned on mid-dark covers; a near-white one landed the card in
            // the mid-tone dead zone where NEITHER white nor black clears AA
            // across the gradient (3.70:1 white on the top stop, 3.37:1 black on
            // the bottom). Dimming bright covers further puts the card back
            // where white text is comfortable, and leaves darker covers alone.
            let scale = Self.darkDimming(forLuminance: dominant.relativeLuminance(in: scheme))
            topSolid = Color(red: r * scale, green: g * scale, blue: b * scale)
            let bottomScale = scale * (0.40 / 0.55)
            bottomSolid = Color(red: r * bottomScale, green: g * bottomScale, blue: b * bottomScale)
        } else {
            // Tint white WITH the cover instead. Reusing the dark multipliers on
            // a white page renders every card as a dark slab; blending toward
            // white keeps the era's identity and reads as tinted paper.
            topSolid = dominant.blended(with: .white, fraction: 0.68, in: scheme)
            bottomSolid = dominant.blended(with: .white, fraction: 0.82, in: scheme)
        }
        let top = topSolid.opacity(0.95)
        let bottom = bottomSolid.opacity(0.90)

        // Decide the title against the LIGHTER of the two stops — the one where
        // light-on-light fails. Deriving it from a separate "effective" mix
        // instead let a dark cover in the light appearance resolve to white text
        // on a near-white card (Harry Styles "Untitled Era 4").
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
