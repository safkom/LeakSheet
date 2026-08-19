import SwiftUI

// MARK: - App Colors

extension Color {
    // MARK: - Appearance

    /// An appearance-aware colour.
    ///
    /// SwiftUI has no cross-platform dynamic `Color` initialiser, so the fork
    /// lives here once and every token below is built from it. Asset-catalog
    /// colour sets would work too, but 30 of them is a lot of JSON to keep in
    /// step with the HSB literals the badge palette is actually derived from.
    static func adaptive(light: Color, dark: Color) -> Color {
        #if canImport(AppKit)
        Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
                ? NSColor(dark) : NSColor(light)
        })
        #else
        Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(dark) : UIColor(light)
        })
        #endif
    }

    /// A palette tone: one hue, two appearances.
    ///
    /// Every badge/credit/filter colour is used as TEXT on a low-opacity wash of
    /// itself (`BadgePill`, `CreditTagsView`). The tuned values sit at brightness
    /// 0.75–0.96, which is right on black and illegible on white — so the light
    /// appearance keeps the hue, nudges saturation up and drops brightness into
    /// AA range instead of hand-authoring 30 second literals.
    ///
    /// `dark` is the original value verbatim; the dark appearance is unchanged.
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

    /// App background.
    ///
    /// iPhone keeps OLED black (it is a real power saving on that panel and the
    /// design was drawn for it). A desktop display has no such payoff and a
    /// full-window pure black reads as a phone app blown up, so the Mac sits a
    /// few points off zero.
    static let lsBackground = adaptive(light: Color(hex: 0xFFFFFF), dark: macDark(0x141414, iOS: 0x000000))
    static let lsCard = adaptive(light: Color(hex: 0xF2F2F5), dark: macDark(0x1C1C1C, iOS: 0x0F0F0F))
    static let lsBorder = adaptive(light: Color(hex: 0xD9D9DE), dark: Color(hex: 0x242424))

    // Text
    static let lsDim = adaptive(light: Color(hex: 0x8E8E93), dark: Color(hex: 0x595959))

    // Accent
    static let lsPrimary = tone(hue: 220 / 360, saturation: 0.655, brightness: 0.96, lightBrightness: 0.74)

    // Semantic
    static let lsAccent = lsPrimary
    static let lsError = adaptive(light: Color(hex: 0xC0342D), dark: Color(hex: 0xF85149))
    static let lsFavourite = adaptive(light: Color(hex: 0xC2264A), dark: Color(hex: 0xE84057))

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
    static let badgeRumored = tone(hue: 40 / 360, saturation: 0.45, brightness: 0.86, lightBrightness: 0.44)      // tentative amber
    static let badgeConflicting = tone(hue: 15 / 360, saturation: 0.55, brightness: 0.88)  // disputed red-amber

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
    case og, lossless, hq, cd, lq, rec, beatonly, na
    case ogfile, full, tagged, stem, partial, snippet, confirmed, unavailable
    case rumored, conflicting
    /// Not a quality/availability value — the content-tab entry type
    /// ("MUSIC VIDEO", "STEM"), which had its own bespoke pill before.
    case accent

    var color: Color {
        switch self {
        case .og: .badgeOG
        case .lossless: .badgeLossless
        case .hq: .badgeHQ
        case .cd: .badgeCD
        case .lq: .badgeLQ
        case .rec: .badgeRec
        case .beatonly: .badgeBeatOnly
        case .na: .badgeNA
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
        case .accent: .lsAccent
        }
    }

    var background: Color {
        color.opacity(0.15)
    }
}

func qualityVariant(_ quality: String?) -> BadgeVariant {
    guard let q = quality?.lowercased() else { return .na }
    if q.contains("lossless") { return .lossless }
    if q.contains("og") { return .og }
    if q.contains("cd") { return .cd }
    if q.contains("high") { return .hq }
    if q.contains("low") { return .lq }
    if q.contains("recording") { return .rec }
    if q.contains("beat") { return .beatonly }
    return .na
}

func availabilityVariant(_ avail: String?) -> BadgeVariant {
    guard let a = avail?.lowercased() else { return .na }
    if a.contains("og file") { return .ogfile }
    if a == "full" { return .full }
    if a.contains("tagged") { return .tagged }
    if a.contains("stem") { return .stem }
    if a.contains("beat") { return .beatonly }
    if a.contains("partial") || a.contains("cut") { return .partial }
    if a.contains("snippet") { return .snippet }
    if a.contains("rumo") { return .rumored }  // rumored + British "rumoured"
    if a.contains("conflicting") { return .conflicting }
    if a.contains("confirmed") { return .confirmed }
    if a.contains("unavailable") { return .unavailable }
    return .na
}

// MARK: - Color Utilities

extension Color {
    /// Extract sRGB components (0–1 range) as they resolve in `scheme`.
    ///
    /// Uses SwiftUI's own `resolve(in:)` rather than `UIColor(self)` — the
    /// UIKit round-trip has no macOS equivalent.
    /// See DECISIONS.md::DesignTokens.swift::color-resolve.
    ///
    /// The scheme is a parameter, not a constant, because the palette above is
    /// appearance-aware: resolving `.lsBackground` in the wrong scheme hands the
    /// contrast maths the opposite backdrop and every derived colour inverts.
    /// It defaults to `.dark` so the pinned literal tests keep their meaning.
    func rgbComponents(in scheme: ColorScheme = .dark) -> (red: Double, green: Double, blue: Double) {
        var env = EnvironmentValues()
        env.colorScheme = scheme
        let c = resolve(in: env)
        return (Double(c.red), Double(c.green), Double(c.blue))
    }

    /// Shift every channel by `amount`, clamped to 0…1. Negative darkens.
    func brightened(by amount: Double, in scheme: ColorScheme = .dark) -> Color {
        let (r, g, b) = rgbComponents(in: scheme)
        func clamp(_ v: Double) -> Double { min(max(v + amount, 0), 1) }
        return Color(red: clamp(r), green: clamp(g), blue: clamp(b))
    }

    /// WCAG relative luminance (0 = black, 1 = white).
    func relativeLuminance(in scheme: ColorScheme = .dark) -> Double {
        let (r, g, b) = rgbComponents(in: scheme)
        func linearize(_ c: Double) -> Double {
            c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)
    }

    /// WCAG contrast ratio (1:1 = identical, 21:1 = max).
    func contrastRatio(against other: Color, in scheme: ColorScheme = .dark) -> Double {
        let l1 = max(relativeLuminance(in: scheme), other.relativeLuminance(in: scheme))
        let l2 = min(relativeLuminance(in: scheme), other.relativeLuminance(in: scheme))
        return (l1 + 0.05) / (l2 + 0.05)
    }

    /// Step away from `background` until WCAG AA contrast is met.
    ///
    /// Direction follows the backdrop: brighten on a dark one, darken on a light
    /// one. Brightening only — which is what this did while the app was
    /// force-dark — walks a colour on a white page *toward* white and never
    /// converges. Falls back to `.primary` if 20 steps can't reach the target.
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

    /// Returns near-white or near-black depending on background luminance —
    /// guaranteed-legible body/title text for any backdrop color.
    static func preferredText(on background: Color, in scheme: ColorScheme = .dark) -> Color {
        background.relativeLuminance(in: scheme) < 0.5 ? Color.white : Color.black
    }

    /// Linear blend toward `other` (0 = self, 1 = other). Used to approximate
    /// the effective backdrop where a gradient sits between two colors.
    func blended(with other: Color, fraction: Double, in scheme: ColorScheme = .dark) -> Color {
        let f = min(max(fraction, 0), 1)
        let (r1, g1, b1) = rgbComponents(in: scheme)
        let (r2, g2, b2) = other.rgbComponents(in: scheme)
        return Color(
            red: r1 + (r2 - r1) * f,
            green: g1 + (g2 - g1) * f,
            blue: b1 + (b2 - b1) * f
        )
    }

    // MARK: - Filter-specific accent colors

    static let filterBestOf = tone(hue: 45 / 360, saturation: 0.85, brightness: 0.90, lightBrightness: 0.46)
    static let filterGrail = tone(hue: 43 / 360, saturation: 0.92, brightness: 0.96, lightBrightness: 0.44)   // trophy gold (grails + wanted)
    static let filterRecent = tone(hue: 140 / 360, saturation: 0.70, brightness: 0.80, lightBrightness: 0.42)
    static let filterNoSnippets = tone(hue: 280 / 360, saturation: 0.60, brightness: 0.85)
    static let filterMisc = tone(hue: 200 / 360, saturation: 0.65, brightness: 0.85)
}

// MARK: - Shared formatters

/// Tiny cross-cutting formatters with one definition each — these were
/// previously copy-pasted across the player, description sheet, and landing
/// views, and had already drifted apart.
nonisolated enum Format {
    /// Seconds → "m:ss" (e.g. 139.8 → "2:19").
    static func time(_ seconds: TimeInterval) -> String {
        guard seconds.isFinite && seconds >= 0 else { return "0:00" }
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return "\(mins):\(String(format: "%02d", secs))"
    }

    /// Host without the "www." prefix, for compact link labels. Strips only a
    /// leading "www." — the old copies used replacingOccurrences, which also
    /// mangled hosts containing "www." mid-string.
    static func shortHost(_ urlString: String) -> String {
        guard let url = URL(string: urlString), let host = url.host else { return urlString }
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    /// Up to two uppercased initials from a display name.
    static func initials(_ name: String) -> String {
        name.split(separator: " ")
            .prefix(2)
            .compactMap { $0.first.map { String($0).uppercased() } }
            .joined()
    }
}

// MARK: - String Slugify

extension String {
    /// Derive a URL-safe slug from a name (lowercase, spaces → hyphens, strip non-alphanumeric).
    var slugified: String {
        lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .filter { $0.isLetter || $0.isNumber || $0 == "-" }
    }
}

// MARK: - Credit Tag Colors

enum CreditType: String {
    case featuring, producers, collaboration, refs, director, creditedArtists

    var color: Color {
        switch self {
        // Dark brightnesses raised where the shipped value could not clear AA
        // on its own tag (producers 3.67:1, creditedArtists 3.87:1,
        // director 3.45:1). Hues are unchanged, so the credits still read as
        // the same six colours.
        case .featuring: .tone(hue: 200 / 360, saturation: 0.60, brightness: 0.78, lightBrightness: 0.46)
        case .producers: .tone(hue: 280 / 360, saturation: 0.50, brightness: 0.87, lightBrightness: 0.46)
        case .collaboration: .tone(hue: 160 / 360, saturation: 0.50, brightness: 0.72, lightBrightness: 0.38)
        case .refs: .tone(hue: 30 / 360, saturation: 0.60, brightness: 0.78, lightBrightness: 0.44)
        case .director: .tone(hue: 250 / 360, saturation: 0.45, brightness: 0.90, lightBrightness: 0.48)
        case .creditedArtists: .tone(hue: 340 / 360, saturation: 0.50, brightness: 0.84, lightBrightness: 0.46)
        }
    }

    var label: String {
        switch self {
        case .featuring: "feat."
        case .producers: "prod."
        case .collaboration: "with"
        case .refs: "ref."
        case .director: "dir."
        case .creditedArtists: "artist"
        }
    }

    /// Spoken form for VoiceOver — the abbreviated visual label reads poorly.
    var accessibilityLabel: String {
        switch self {
        case .featuring: "Featuring"
        case .producers: "Produced by"
        case .collaboration: "With"
        case .refs: "Reference by"
        case .director: "Directed by"
        case .creditedArtists: "Artist"
        }
    }
}
