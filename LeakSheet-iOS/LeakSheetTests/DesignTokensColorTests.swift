import SwiftUI
import Testing

@testable import LeakSheet

/// Pins `Color.rgbComponents` after it moved off `UIColor(self)` onto SwiftUI's
/// own `resolve(in:)` (the UIKit round-trip has no macOS equivalent), and pins
/// the contrast guarantees the appearance-aware palette rests on.
///
/// The expected values are the exact sRGB components of the literals in
/// DesignTokens.swift. If `resolve(in:)` ever differs from the declared color,
/// every derived value — `brightened`, `relativeLuminance`, `contrastRatio`,
/// `ensureReadable` — shifts, and era-card text contrast changes app-wide.
@Suite("Design token colors")
struct DesignTokensColorTests {
    /// sRGB components are exact for hex literals, so the tolerance only needs
    /// to absorb Float→Double widening.
    private let tolerance = 0.002

    private func expectComponents(
        _ color: Color,
        _ expected: (Double, Double, Double),
        _ label: String,
        sourceLocation: SourceLocation = #_sourceLocation
    ) {
        let (r, g, b) = color.rgbComponents()
        #expect(abs(r - expected.0) < tolerance, "\(label) red", sourceLocation: sourceLocation)
        #expect(abs(g - expected.1) < tolerance, "\(label) green", sourceLocation: sourceLocation)
        #expect(abs(b - expected.2) < tolerance, "\(label) blue", sourceLocation: sourceLocation)
    }

    @Test("Hex literals round-trip exactly")
    func hexLiterals() {
        expectComponents(.lsBorder, (0x24 / 255, 0x24 / 255, 0x24 / 255), "lsBorder")
        expectComponents(.lsDim, (0x59 / 255, 0x59 / 255, 0x59 / 255), "lsDim")
        expectComponents(.lsError, (0xF8 / 255, 0x51 / 255, 0x49 / 255), "lsError")
        expectComponents(.lsFavourite, (0xE8 / 255, 0x40 / 255, 0x57 / 255), "lsFavourite")
    }

    @Test("HSB literals resolve to their RGB equivalent")
    func hsbLiterals() {
        // lsPrimary: hue 220/360, sat 0.655, bri 0.96 → ~#548AF5
        expectComponents(.lsPrimary, (0.331, 0.541, 0.96), "lsPrimary")
        // badgeOG: hue 40/360, sat 0.90, bri 0.96
        expectComponents(.badgeOG, (0.96, 0.672, 0.096), "badgeOG")
        // Pure greyscale: saturation 0 means all three channels equal brightness.
        expectComponents(.badgeNA, (0.92, 0.92, 0.92), "badgeNA")
    }

    /// The whole point of `adaptive`: the dark appearance must be byte-identical
    /// to what shipped, and the light one must actually differ. A dynamic colour
    /// that ignored `resolve(in:)`'s scheme would pass the pins above while
    /// silently rendering the dark palette on a white page.
    @Test("Adaptive tokens resolve differently per appearance")
    func adaptiveResolvesPerScheme() {
        for (color, label) in [
            (Color.lsBackground, "lsBackground"),
            (Color.lsCard, "lsCard"),
            (Color.badgeOG, "badgeOG"),
            (Color.lsAccent, "lsAccent"),
        ] {
            let dark = color.rgbComponents(in: .dark)
            let light = color.rgbComponents(in: .light)
            #expect(dark != light, "\(label) resolves identically in both appearances")
        }
        // Backgrounds must actually swap ends of the luminance scale.
        #expect(Color.lsBackground.relativeLuminance(in: .dark) < 0.05)
        #expect(Color.lsBackground.relativeLuminance(in: .light) > 0.8)
    }

    @Test("Black and white anchor the luminance scale")
    func luminanceAnchors() {
        #expect(Color.black.relativeLuminance() < 0.001)
        #expect(Color.white.relativeLuminance() > 0.999)
        #expect(abs(Color.white.contrastRatio(against: .black) - 21.0) < 0.01)
    }

    @Test("ensureReadable reaches AA contrast in both appearances", arguments: [ColorScheme.dark, .light])
    func ensureReadable(scheme: ColorScheme) {
        // A colour that starts far below AA against this scheme's background:
        // near-black on dark, near-white on light. Brightening-only maths
        // converges on the first and diverges on the second.
        let start = scheme == .dark ? Color(hex: 0x1A1A1A) : Color(hex: 0xF2F2F2)
        let fixed = start.ensureReadable(against: .lsBackground, in: scheme)
        #expect(fixed.contrastRatio(against: .lsBackground, in: scheme) >= 4.5)
    }

    @Test("preferredText picks the higher-contrast candidate")
    func preferredText() {
        #expect(Color.preferredText(on: .black).rgbComponents().red > 0.9)
        #expect(Color.preferredText(on: .white).rgbComponents().red < 0.1)
        // Mid-grey: "dark" by the old 0.5 midpoint test, but black wins on
        // actual contrast (5.7:1 vs 3.7:1).
        let midGrey = Color(hex: 0x868686)
        #expect(Color.preferredText(on: midGrey).rgbComponents().red < 0.1)
        // Whichever it picks must be the better of the two, everywhere.
        for value in stride(from: 0.0, through: 1.0, by: 0.05) {
            let backdrop = Color(red: value, green: value, blue: value)
            let picked = Color.preferredText(on: backdrop)
            let other: Color = picked.rgbComponents().red > 0.5 ? .black : .white
            #expect(picked.contrastRatio(against: backdrop) >= other.contrastRatio(against: backdrop))
        }
    }

    // MARK: - Palette contrast

    // Each group below composites the way its call site actually does. Modelling
    // them all as one 15% pill would flag colours that are never drawn that way
    // and miss the ones that are drawn differently.

    /// `BadgePill`: full-opacity text on a 15% wash of itself over the app
    /// background. This is what has to clear AA — in BOTH appearances, or the
    /// light palette is 30 unverified guesses.
    @Test("Badge pills clear AA", arguments: [ColorScheme.dark, .light])
    func badgePillContrast(scheme: ColorScheme) {
        for (color, label) in Self.badgeTones {
            let pill = color.blended(with: .lsBackground, fraction: 0.85, in: scheme)
            expectAA(color, on: pill, label, scheme)
        }
    }

    /// `CreditTagsView` composites exactly like `BadgePill` — same wash, same
    /// text opacity — so one model covers both.
    @Test("Credit tags clear AA", arguments: [ColorScheme.dark, .light])
    func creditTagContrast(scheme: ColorScheme) {
        for (color, label) in Self.creditTones {
            let tag = color.blended(with: .lsBackground, fraction: 0.85, in: scheme)
            expectAA(color, on: tag, label, scheme)
        }
    }

    /// Plain text drawn straight on the app background.
    @Test("Body tones clear AA on the app background", arguments: [ColorScheme.dark, .light])
    func onBackgroundContrast(scheme: ColorScheme) {
        for (color, label) in [(Color.lsError, "lsError"), (.lsAccent, "lsAccent"), (.lsFavourite, "lsFavourite")] {
            expectAA(color, on: .lsBackground, label, scheme)
        }
    }

    private func expectAA(
        _ color: Color, on background: Color, _ label: String, _ scheme: ColorScheme,
        sourceLocation: SourceLocation = #_sourceLocation
    ) {
        let ratio = color.contrastRatio(against: background, in: scheme)
        #expect(
            ratio >= 4.5,
            "\(label) reads at \(String(format: "%.2f", ratio)):1 in \(scheme)",
            sourceLocation: sourceLocation
        )
    }

    /// Named rather than derived from `BadgeVariant.allCases` — the enum has no
    /// CaseIterable conformance and adding one just for a test is the tail
    /// wagging the dog. `.accent` maps to `lsAccent`, covered above.
    private static let badgeTones: [(Color, String)] = [
        (.badgeOG, "badgeOG"), (.badgeLossless, "badgeLossless"), (.badgeHQ, "badgeHQ"),
        (.badgeCD, "badgeCD"), (.badgeLQ, "badgeLQ"), (.badgeNA, "badgeNA"), (.badgeRec, "badgeRec"),
        (.badgeOGFile, "badgeOGFile"), (.badgeFull, "badgeFull"), (.badgeTagged, "badgeTagged"),
        (.badgePartial, "badgePartial"), (.badgeSnippet, "badgeSnippet"),
        (.badgeConfirmed, "badgeConfirmed"), (.badgeBeatOnly, "badgeBeatOnly"),
        (.badgeStem, "badgeStem"), (.badgeUnavailable, "badgeUnavailable"),
        (.badgeRumored, "badgeRumored"), (.badgeConflicting, "badgeConflicting"),
        (.lsAccent, "lsAccent"),
    ]

    private static let creditTones: [(Color, String)] = [
        (CreditType.featuring.color, "credit.featuring"),
        (CreditType.producers.color, "credit.producers"),
        (CreditType.collaboration.color, "credit.collaboration"),
        (CreditType.refs.color, "credit.refs"),
        (CreditType.director.color, "credit.director"),
        (CreditType.creditedArtists.color, "credit.creditedArtists"),
    ]
}

/// Era card title legibility.
///
/// The card is a two-stop gradient of the cover's dominant colour. The title has
/// to clear AA against BOTH stops, not against some intermediate mix — a dark
/// cover in the light appearance produced white text on a near-white card
/// because the decision was made against a separate blend.
@Suite("Era card contrast")
@MainActor
struct EraDisplayColorsContrastTests {
    /// Covers the range of dominant colours extraction actually yields: near
    /// black, near white, saturated, and desaturated mid-tones.
    private static let dominants: [(Color, String)] = [
        (Color(hex: 0x101014), "near-black"),
        (Color(hex: 0xF4F1EC), "near-white"),
        (Color(hex: 0xE02020), "saturated red"),
        (Color(hex: 0x1E3A8A), "deep navy"),
        (Color(hex: 0x7A7A7A), "mid grey"),
        (Color(hex: 0xC9A227), "gold"),
        (Color(hex: 0x2F6B4F), "forest"),
    ]

    @Test("Card title clears AA on both gradient stops", arguments: [ColorScheme.dark, .light])
    func titleContrast(scheme: ColorScheme) {
        for (dominant, label) in Self.dominants {
            let colors = EraDisplayColors.derive(from: dominant, in: scheme)
            for (stop, which) in [(colors.gradientTop, "top"), (colors.gradientBottom, "bottom")] {
                let ratio = colors.title.contrastRatio(against: stop, in: scheme)
                #expect(ratio >= 4.5, "\(label) title on \(which) stop: \(String(format: "%.2f", ratio)):1 in \(scheme)")
            }
        }
    }
}
