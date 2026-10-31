import SwiftUI

// MARK: - App Colors

extension Color {
    // MARK: - Appearance

    /// An appearance-aware colour: see DECISIONS.md::DesignTokens.swift::adaptive-palette
    ///
    /// `nonisolated`, with both platform colours built BEFORE the provider: SwiftUI
    /// resolves colours off-main, where a MainActor-inferred provider traps (SIGTRAP).
    nonisolated static func adaptive(light: Color, dark: Color) -> Color {
        #if canImport(AppKit)
        let lightColor = NSColor(light)
        let darkColor = NSColor(dark)
        return Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? darkColor : lightColor
        })
        #else
        let lightColor = UIColor(light)
        let darkColor = UIColor(dark)
        return Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark ? darkColor : lightColor
        })
        #endif
    }

    /// A palette tone: one hue, two appearances.
    ///
    /// Tones are TEXT on a low-opacity wash of themselves, and the tuned brightness
    /// (0.75–0.96) is illegible on white, so the light appearance keeps the hue, nudges
    /// saturation up and drops brightness into AA range. `dark` is used verbatim.
    static func tone(
        hue: Double,
        saturation: Double,
        brightness: Double,
        lightBrightness: Double = 0.52
    ) -> Color {
        adaptive(
            light: Color(hue: hue, saturation: min(saturation * 1.08, 1), brightness: lightBrightness),
            dark: Color(hue: hue, saturation: saturation, brightness: brightness)
        )
    }

    // MARK: - Core palette

    /// App background: OLED black on iPhone (a real power saving); the Mac sits a few
    /// points off zero, since full-window pure black reads as a blown-up phone app.
    static let lsBackground = adaptive(light: Color(hex: 0xFFFFFF), dark: macDark(0x141414, iOS: 0x000000))
    static let lsCard = adaptive(light: Color(hex: 0xF2F2F5), dark: macDark(0x1C1C1C, iOS: 0x0F0F0F))
    static let lsBorder = adaptive(light: Color(hex: 0xD9D9DE), dark: Color(hex: 0x242424))

    // Text
    static let lsDim = adaptive(light: Color(hex: 0x8E8E93), dark: Color(hex: 0x595959))

    // Accent
    static let lsPrimary = tone(hue: 220 / 360, saturation: 0.655, brightness: 0.96, lightBrightness: 0.74)

    /// Selected-row fill for the macOS list: a neutral lifted row rather than the
    /// saturated system accent.
    ///
    /// Two static values, not one `adaptive` colour: a list ignores a tint built from a
    /// dynamic platform colour and falls back to the accent. The caller picks by scheme.
    static let lsSelectionDark = Color(hex: 0x3A3A3C)
    static let lsSelectionLight = Color(hex: 0xD6D6DB)

    static func lsSelection(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? lsSelectionDark : lsSelectionLight
    }

    // Semantic
    static let lsAccent = lsPrimary
    static let lsError = adaptive(light: Color(hex: 0xC0342D), dark: Color(hex: 0xF85149))
    static let lsFavourite = adaptive(light: Color(hex: 0xC2264A), dark: Color(hex: 0xE84057))
    /// Positive numbers ("Available"); system green fails AA on white.
    static let lsSuccess = adaptive(light: Color(hex: 0x1F7A33), dark: Color(hex: 0x3FB950))
    /// Caution text ("outdated", an invalid setting); system orange fails AA on white.
    static let lsWarning = adaptive(light: Color(hex: 0xA35200), dark: Color(hex: 0xFFA032))
    /// Star glyphs; system yellow is near-invisible on white.
    static let lsStar = adaptive(light: Color(hex: 0xB07D00), dark: Color(hex: 0xFFD60A))

    /// Picks between two dark-appearance values by platform.
    private static func macDark(_ mac: UInt, iOS: UInt) -> Color {
        #if os(macOS)
        Color(hex: mac)
        #else
        Color(hex: iOS)
        #endif
    }

    // MARK: - Badge Colors

    // Quality badges
    static let badgeOG = tone(hue: 40 / 360, saturation: 0.90, brightness: 0.96)
    static let badgeLossless = tone(hue: 200 / 360, saturation: 0.85, brightness: 0.96)
    static let badgeHQ = tone(hue: 50 / 360, saturation: 0.92, brightness: 0.96, lightBrightness: 0.44)
    static let badgeCD = tone(hue: 130 / 360, saturation: 0.55, brightness: 0.95, lightBrightness: 0.42)
    static let badgeLQ = tone(hue: 0 / 360, saturation: 0.67, brightness: 0.96)
    static let badgeNA = tone(hue: 0 / 360, saturation: 0.0, brightness: 0.92, lightBrightness: 0.38)
    static let badgeRec = tone(hue: 30 / 360, saturation: 0.65, brightness: 0.95)

    // Availability badges
    static let badgeOGFile = tone(hue: 140 / 360, saturation: 0.55, brightness: 0.95, lightBrightness: 0.40)
    static let badgeFull = tone(hue: 215 / 360, saturation: 0.70, brightness: 0.96)
    static let badgeTagged = tone(hue: 150 / 360, saturation: 0.55, brightness: 0.95, lightBrightness: 0.40)
    static let badgePartial = tone(hue: 50 / 360, saturation: 0.92, brightness: 0.96, lightBrightness: 0.44)
    static let badgeSnippet = tone(hue: 0 / 360, saturation: 0.67, brightness: 0.96)
    static let badgeConfirmed = tone(hue: 0 / 360, saturation: 0.0, brightness: 0.95, lightBrightness: 0.38)
    static let badgeBeatOnly = tone(hue: 275 / 360, saturation: 0.50, brightness: 0.96)
    static let badgeStem = tone(hue: 270 / 360, saturation: 0.50, brightness: 0.96)
    static let badgeUnavailable = tone(hue: 0 / 360, saturation: 0.0, brightness: 0.88, lightBrightness: 0.40)
    // tentative amber
    static let badgeRumored = tone(hue: 40 / 360, saturation: 0.45, brightness: 0.86, lightBrightness: 0.44)
    static let badgeConflicting = tone(hue: 15 / 360, saturation: 0.55, brightness: 0.88)  // disputed red-amber

    // Content-tab entry type ("Production", "Music Video"). Deliberately neutral:
    // on song rows colour means status (quality or availability), not kind.
    static let badgeEntryType = tone(hue: 0 / 360, saturation: 0.0, brightness: 0.72, lightBrightness: 0.40)

    // MARK: - Hex Initializer

    init(hex: UInt, opacity: Double = 1.0) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }
}

// MARK: - Badge Variant Mapping

enum BadgeVariant: String {
    case original = "og", lossless, highQuality = "hq", cdQuality = "cd", lowQuality = "lq", rec, beatonly
    case notAvailable = "na"
    case ogfile, full, tagged, stem, partial, snippet, confirmed, unavailable
    case rumored, conflicting
    /// Not a quality/availability value — the content-tab entry type
    /// ("Production", "Music Video").
    case entryType

    var color: Color {
        switch self {
        case .original: .badgeOG
        case .lossless: .badgeLossless
        case .highQuality: .badgeHQ
        case .cdQuality: .badgeCD
        case .lowQuality: .badgeLQ
        case .rec: .badgeRec
        case .beatonly: .badgeBeatOnly
        case .notAvailable: .badgeNA
        case .ogfile: .badgeOGFile
        case .full: .badgeFull
        case .tagged: .badgeTagged
        case .stem: .badgeStem
        case .partial: .badgePartial
        case .snippet: .badgeSnippet
        case .confirmed: .badgeConfirmed
        case .unavailable: .badgeUnavailable
        case .rumored: .badgeRumored
        case .conflicting: .badgeConflicting
        case .entryType: .badgeEntryType
        }
    }

    var background: Color {
        color.opacity(0.15)
    }
}

func qualityVariant(_ quality: String?) -> BadgeVariant {
    guard let qual = quality?.lowercased() else { return .notAvailable }
    if qual.contains("lossless") || qual.contains("flac") || qual.contains("wav") { return .lossless }
    if qual.contains("og") { return .original }
    if qual.contains("cd") { return .cdQuality }
    if qual.contains("high") { return .highQuality }
    if qual.contains("low") { return .lowQuality }
    if qual.contains("recording") { return .rec }
    if qual.contains("beat") { return .beatonly }
    // Short forms are whole words only; Russian-language trackers name the tiers too.
    if qual.contains(/\bhq\b/) || qual.contains("высок") { return .highQuality }
    if qual.contains(/\blq\b/) || qual.contains("низк") { return .lowQuality }
    return .notAvailable
}

/// Availability wording → variant, first match wins.
private nonisolated let availabilityRules: [(matches: @Sendable (String) -> Bool, variant: BadgeVariant)] = [
    ({ $0.contains("og file") || $0.contains("original file") }, .ogfile),
    ({ $0 == "full" }, .full),
    ({ $0.contains("tagged") }, .tagged),
    ({ $0.contains("stem") }, .stem),
    ({ $0.contains("beat") }, .beatonly),
    ({ $0.contains("partial") || $0.contains("cut") }, .partial),
    ({ $0.contains("snippet") }, .snippet),
    ({ $0.contains("rumo") }, .rumored),  // rumored + British "rumoured"
    ({ $0.contains("conflicting") }, .conflicting),
    ({ $0.contains("confirmed") }, .confirmed),
    ({ $0.contains("unavailable") || $0.contains(/\blost\b/) }, .unavailable),
    // Compound values ("Full Lossless") land here; without this they'd paint neutral
    // grey beside a blue "Full". Last, so it never outranks a more specific match.
    ({ $0.contains("full") }, .full),
    ({ $0.contains("lossless") }, .lossless)
]

func availabilityVariant(_ avail: String?) -> BadgeVariant {
    guard let lowered = avail?.lowercased() else { return .notAvailable }
    return availabilityRules.first { $0.matches(lowered) }?.variant ?? .notAvailable
}

// MARK: - Color Utilities

extension Color {
    /// Extract sRGB components (0–1 range) as they resolve in `scheme`.
    ///
    /// See DECISIONS.md::DesignTokens.swift::color-resolve and ::scheme-parameter.
    /// Defaults to `.dark` so the pinned literal tests keep their meaning.
    func rgbComponents(in scheme: ColorScheme = .dark) -> (red: Double, green: Double, blue: Double) {
        var env = EnvironmentValues()
        env.colorScheme = scheme
        let resolved = resolve(in: env)
        return (Double(resolved.red), Double(resolved.green), Double(resolved.blue))
    }

    /// Shift every channel by `amount`, clamped to 0…1. Negative darkens.
    func brightened(by amount: Double, in scheme: ColorScheme = .dark) -> Color {
        let (redValue, greenValue, blueValue) = rgbComponents(in: scheme)
        func clamp(_ component: Double) -> Double { min(max(component + amount, 0), 1) }
        return Color(red: clamp(redValue), green: clamp(greenValue), blue: clamp(blueValue))
    }

    /// WCAG relative luminance (0 = black, 1 = white).
    func relativeLuminance(in scheme: ColorScheme = .dark) -> Double {
        let (red, green, blue) = rgbComponents(in: scheme)
        func linearize(_ channel: Double) -> Double {
            channel <= 0.03928 ? channel / 12.92 : pow((channel + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linearize(red) + 0.7152 * linearize(green) + 0.0722 * linearize(blue)
    }

    /// WCAG contrast ratio (1:1 = identical, 21:1 = max).
    func contrastRatio(against other: Color, in scheme: ColorScheme = .dark) -> Double {
        let lighter = max(relativeLuminance(in: scheme), other.relativeLuminance(in: scheme))
        let darker = min(relativeLuminance(in: scheme), other.relativeLuminance(in: scheme))
        return (lighter + 0.05) / (darker + 0.05)
    }

    /// Step away from `background` until WCAG AA contrast is met: brighten on a dark
    /// backdrop, darken on a light one. Falls back to `.primary` after 20 steps.
    func ensureReadable(
        against background: Color,
        minRatio: Double = 4.5,
        in scheme: ColorScheme = .dark
    ) -> Color {
        let step = background.relativeLuminance(in: scheme) < 0.5 ? 0.06 : -0.06
        var current = self
        for _ in 0..<20 {
            if current.contrastRatio(against: background, in: scheme) >= minRatio { return current }
            current = current.brightened(by: step, in: scheme)
        }
        return .primary
    }

    /// White or black — whichever actually contrasts more with `background`.
    /// See DECISIONS.md::DesignTokens.swift::preferred-text-crossover.
    static func preferredText(on background: Color, in scheme: ColorScheme = .dark) -> Color {
        let luminance = background.relativeLuminance(in: scheme)
        let againstWhite = 1.05 / (luminance + 0.05)
        let againstBlack = (luminance + 0.05) / 0.05
        return againstWhite >= againstBlack ? Color.white : Color.black
    }

    /// Linear blend toward `other` (0 = self, 1 = other). Used to approximate
    /// the effective backdrop where a gradient sits between two colors.
    func blended(with other: Color, fraction: Double, in scheme: ColorScheme = .dark) -> Color {
        let amount = min(max(fraction, 0), 1)
        let (red1, green1, blue1) = rgbComponents(in: scheme)
        let (red2, green2, blue2) = other.rgbComponents(in: scheme)
        return Color(
            red: red1 + (red2 - red1) * amount,
            green: green1 + (green2 - green1) * amount,
            blue: blue1 + (blue2 - blue1) * amount
        )
    }

    /// OKLab (Björn Ottosson) of the resolved sRGB colour.
    private func oklab(in scheme: ColorScheme) -> (L: Double, a: Double, b: Double) {
        let (red, green, blue) = rgbComponents(in: scheme)
        func linear(_ channel: Double) -> Double { channel <= 0.04045 ? channel / 12.92 : pow(
            (channel + 0.055) / 1.055,
            2.4
        ) }
        let (linRed, linGreen, linBlue) = (linear(red), linear(green), linear(blue))
        let lCone = cbrt(0.4122214708 * linRed + 0.5363325363 * linGreen + 0.0514459929 * linBlue)
        let mCone = cbrt(0.2119034982 * linRed + 0.6806995451 * linGreen + 0.1073969566 * linBlue)
        let sCone = cbrt(0.0883024619 * linRed + 0.2817188376 * linGreen + 0.6299787005 * linBlue)
        return (0.2104542553 * lCone + 0.7936177850 * mCone - 0.0040720468 * sCone,
                1.9779984951 * lCone - 2.4285922050 * mCone + 0.4505937099 * sCone,
                0.0259040371 * lCone + 0.7827717662 * mCone - 0.8086757660 * sCone)
    }

    /// This colour's hue at `reference`'s perceptual lightness, chroma capped at
    /// `maxChroma`: a black cover tints as visibly as a white one.
    func tint(lightnessOf reference: Color, maxChroma: Double, in scheme: ColorScheme = .dark) -> Color {
        let lightness = reference.oklab(in: scheme).L
        let (_, baseA, baseB) = oklab(in: scheme)
        let chroma = (baseA * baseA + baseB * baseB).squareRoot()
        let scale = chroma > 0 ? min(1, maxChroma / chroma) : 0
        let (aAxis, bAxis) = (baseA * scale, baseB * scale)
        func cube(_ value: Double) -> Double { value * value * value }
        let lCone = cube(lightness + 0.3963377774 * aAxis + 0.2158037573 * bAxis)
        let mCone = cube(lightness - 0.1055613458 * aAxis - 0.0638541728 * bAxis)
        let sCone = cube(lightness - 0.0894841775 * aAxis - 1.2914855480 * bAxis)
        func encode(_ channel: Double) -> Double {
            let clamped = min(max(channel, 0), 1)
            return clamped <= 0.0031308 ? 12.92 * clamped : 1.055 * pow(clamped, 1 / 2.4) - 0.055
        }
        return Color(red: encode(4.0767416621 * lCone - 3.3077115913 * mCone + 0.2309699292 * sCone),
                     green: encode(-1.2684380046 * lCone + 2.6097574011 * mCone - 0.3413193965 * sCone),
                     blue: encode(-0.0041960863 * lCone - 0.7034186147 * mCone + 1.7076147010 * sCone))
    }

    // MARK: - Filter-specific accent colors

    static let filterBestOf = tone(hue: 45 / 360, saturation: 0.85, brightness: 0.90, lightBrightness: 0.46)
    // trophy gold (grails + wanted)
    static let filterGrail = tone(hue: 43 / 360, saturation: 0.92, brightness: 0.96, lightBrightness: 0.44)
    // rust, not Best Of's gold
    static let filterWorstOf = tone(hue: 20 / 360, saturation: 0.45, brightness: 0.80, lightBrightness: 0.40)
    static let filterRecent = tone(hue: 140 / 360, saturation: 0.70, brightness: 0.80, lightBrightness: 0.42)
    static let filterNoSnippets = tone(hue: 280 / 360, saturation: 0.60, brightness: 0.85)
    static let filterMisc = tone(hue: 200 / 360, saturation: 0.65, brightness: 0.85)
}

// MARK: - Shared formatters

// MARK: - String Slugify

// MARK: - Credit Tag Colors
