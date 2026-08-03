import SwiftUI
import Testing

@testable import LeakSheet

/// Pins `Color.rgbComponents` after it moved off `UIColor(self)` onto SwiftUI's
/// own `resolve(in:)` (the UIKit round-trip has no macOS equivalent).
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
        let (r, g, b) = color.rgbComponents
        #expect(abs(r - expected.0) < tolerance, "\(label) red", sourceLocation: sourceLocation)
        #expect(abs(g - expected.1) < tolerance, "\(label) green", sourceLocation: sourceLocation)
        #expect(abs(b - expected.2) < tolerance, "\(label) blue", sourceLocation: sourceLocation)
    }

    @Test("Hex literals round-trip exactly")
    func hexLiterals() {
        expectComponents(.lsCard, (0x0F / 255, 0x0F / 255, 0x0F / 255), "lsCard")
        expectComponents(.lsBorder, (0x24 / 255, 0x24 / 255, 0x24 / 255), "lsBorder")
        expectComponents(.lsDim, (0x59 / 255, 0x59 / 255, 0x59 / 255), "lsDim")
        expectComponents(.lsError, (0xF8 / 255, 0x51 / 255, 0x49 / 255), "lsError")
        expectComponents(.lsFavourite, (0xE8 / 255, 0x40 / 255, 0x57 / 255), "lsFavourite")
    }

    @Test("HSB literals resolve to their RGB equivalent")
    func hsbLiterals() {
        // lsPrimary: hue 220/360, sat 0.70, bri 0.96 → ~#5894F5
        expectComponents(.lsPrimary, (0.288, 0.512, 0.96), "lsPrimary")
        // badgeOG: hue 40/360, sat 0.90, bri 0.96
        expectComponents(.badgeOG, (0.96, 0.672, 0.096), "badgeOG")
        // Pure greyscale: saturation 0 means all three channels equal brightness.
        expectComponents(.badgeNA, (0.92, 0.92, 0.92), "badgeNA")
    }

    @Test("Black and white anchor the luminance scale")
    func luminanceAnchors() {
        #expect(Color.black.relativeLuminance < 0.001)
        #expect(Color.white.relativeLuminance > 0.999)
        #expect(abs(Color.white.contrastRatio(against: .black) - 21.0) < 0.01)
    }

    @Test("ensureReadable reaches AA contrast against the app background")
    func ensureReadable() {
        // A near-black color starts far below AA and must be brightened into range.
        let dim = Color(hex: 0x1A1A1A)
        let fixed = dim.ensureReadable(against: .lsBackground)
        #expect(fixed.contrastRatio(against: .lsBackground) >= 4.5)
    }

    @Test("preferredText flips at the luminance midpoint")
    func preferredText() {
        #expect(Color.preferredText(on: .black).rgbComponents.red > 0.9)
        #expect(Color.preferredText(on: .white).rgbComponents.red < 0.1)
    }
}
