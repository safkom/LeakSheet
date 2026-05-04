import SwiftUI

// MARK: - App Colors

extension Color {
    // Core palette (OLED dark)
    static let lsBackground = Color.black                          // #000000
    static let lsCard = Color(hex: 0x0F0F0F)                     // #0f0f0f
    static let lsCardHover = Color(hex: 0x1A1A1A)                // #1a1a1a
    static let lsBorder = Color(hex: 0x242424)                   // #242424
    static let lsPlayer = Color(hex: 0x080808)                   // #080808

    // Text
    static let lsForeground = Color(hex: 0xE8E8E8)              // #e8e8e8
    static let lsMuted = Color(hex: 0x8C8C8C)                   // #8c8c8c
    static let lsDim = Color(hex: 0x595959)                     // #595959

    // Accent
    static let lsPrimary = Color(hue: 220/360, saturation: 0.70, brightness: 0.96)  // ~#5894f5
    static let lsPrimaryHover = Color(hue: 220/360, saturation: 0.60, brightness: 0.89)

    // Semantic
    static let lsAccent = lsPrimary
    static let lsError = Color(hex: 0xF85149)                   // #f85149
    static let lsFavourite = Color(hex: 0xE84057)               // #e84057

    // MARK: - Badge Colors

    // Quality badges
    static let badgeOG = Color(hue: 40/360, saturation: 0.90, brightness: 0.96)
    static let badgeLossless = Color(hue: 200/360, saturation: 0.85, brightness: 0.96)
    static let badgeHQ = Color(hue: 50/360, saturation: 0.92, brightness: 0.96)
    static let badgeCD = Color(hue: 130/360, saturation: 0.55, brightness: 0.95)
    static let badgeLQ = Color(hue: 0/360, saturation: 0.70, brightness: 0.96)
    static let badgeNA = Color(hue: 0/360, saturation: 0.0, brightness: 0.92)
    static let badgeRec = Color(hue: 30/360, saturation: 0.65, brightness: 0.95)

    // Availability badges
    static let badgeOGFile = Color(hue: 140/360, saturation: 0.55, brightness: 0.95)
    static let badgeFull = Color(hue: 215/360, saturation: 0.70, brightness: 0.96)
    static let badgeTagged = Color(hue: 150/360, saturation: 0.55, brightness: 0.95)
    static let badgePartial = Color(hue: 50/360, saturation: 0.92, brightness: 0.96)
    static let badgeSnippet = Color(hue: 0/360, saturation: 0.70, brightness: 0.96)
    static let badgeConfirmed = Color(hue: 0/360, saturation: 0.0, brightness: 0.95)
    static let badgeBeatOnly = Color(hue: 275/360, saturation: 0.50, brightness: 0.96)
    static let badgeStem = Color(hue: 270/360, saturation: 0.50, brightness: 0.96)
    static let badgeUnavailable = Color(hue: 0/360, saturation: 0.0, brightness: 0.88)

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
        }
    }

    var foreground: Color {
        color
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
    if a.contains("confirmed") { return .confirmed }
    if a.contains("unavailable") { return .unavailable }
    return .na
}

// MARK: - Color Utilities

extension Color {
    /// Extract RGB components (0–1 range) by going through UIColor.
    var rgbComponents: (red: Double, green: Double, blue: Double) {
        let ui = UIColor(self)
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        ui.getRed(&r, green: &g, blue: &b, alpha: &a)
        return (Double(r), Double(g), Double(b))
    }

    /// Return a brightened version of this color (each channel clamped to 1.0).
    func brightened(by amount: Double) -> Color {
        let (r, g, b) = rgbComponents
        return Color(
            red: min(r + amount, 1.0),
            green: min(g + amount, 1.0),
            blue: min(b + amount, 1.0)
        )
    }

    /// WCAG relative luminance (0 = black, 1 = white).
    var relativeLuminance: Double {
        let (r, g, b) = rgbComponents
        func linearize(_ c: Double) -> Double {
            c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)
    }

    /// WCAG contrast ratio (1:1 = identical, 21:1 = max).
    func contrastRatio(against other: Color) -> Double {
        let l1 = max(relativeLuminance, other.relativeLuminance)
        let l2 = min(relativeLuminance, other.relativeLuminance)
        return (l1 + 0.05) / (l2 + 0.05)
    }

    /// Progressively brighten until WCAG AA contrast ratio is met against `background`.
    /// Falls back to `.primary` if 20 iterations can't reach the target.
    func ensureReadable(against background: Color, minRatio: Double = 4.5) -> Color {
        var current = self
        for _ in 0..<20 {
            if current.contrastRatio(against: background) >= minRatio { return current }
            current = current.brightened(by: 0.06)
        }
        return .primary
    }

    /// Returns near-white or near-black depending on background luminance —
    /// guaranteed-legible body/title text for any backdrop color.
    static func preferredText(on background: Color) -> Color {
        background.relativeLuminance < 0.5 ? Color.white : Color.black
    }

    // MARK: - Filter-specific accent colors

    static let filterBestOf = Color(hue: 45/360, saturation: 0.85, brightness: 0.90)
    static let filterRecent = Color(hue: 140/360, saturation: 0.70, brightness: 0.80)
    static let filterNoSnippets = Color(hue: 280/360, saturation: 0.60, brightness: 0.85)
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
    case featuring, producers, collaboration, refs

    var color: Color {
        switch self {
        case .featuring: Color(hue: 200/360, saturation: 0.60, brightness: 0.75)
        case .producers: Color(hue: 280/360, saturation: 0.50, brightness: 0.75)
        case .collaboration: Color(hue: 160/360, saturation: 0.50, brightness: 0.70)
        case .refs: Color(hue: 30/360, saturation: 0.60, brightness: 0.75)
        }
    }

    var label: String {
        switch self {
        case .featuring: "feat."
        case .producers: "prod."
        case .collaboration: "with"
        case .refs: "ref."
        }
    }
}
