import SwiftUI

/// Tiny cross-cutting formatters with one definition each.
nonisolated enum Format {
    /// Seconds → "m:ss" (e.g. 139.8 → "2:19").
    static func time(_ seconds: TimeInterval) -> String {
        guard seconds.isFinite && seconds >= 0 else { return "0:00" }
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return "\(mins):\(String(format: "%02d", secs))"
    }

    /// Host without a leading "www." (only leading), for compact link labels.
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

extension String {
    /// Derive a URL-safe slug from a name (lowercase, spaces → hyphens, strip non-alphanumeric).
    var slugified: String {
        lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .filter { $0.isLetter || $0.isNumber || $0 == "-" }
    }
}

enum CreditType: String {
    case featuring, producers, collaboration, refs, director, engineer, creditedArtists

    // `static let`, not literals in the switch: `Color.tone` builds a dynamic platform
    // colour, and `CreditTagsView` reads `color` twice per tag per body evaluation.
    private static let featuringColor = Color.tone(
        hue: 200 / 360,
        saturation: 0.60,
        brightness: 0.78,
        lightBrightness: 0.46
    )
    private static let producersColor = Color.tone(
        hue: 280 / 360,
        saturation: 0.50,
        brightness: 0.87,
        lightBrightness: 0.46
    )
    private static let collaborationColor = Color.tone(
        hue: 160 / 360,
        saturation: 0.50,
        brightness: 0.72,
        lightBrightness: 0.38
    )
    private static let refsColor = Color.tone(hue: 30 / 360, saturation: 0.60, brightness: 0.78, lightBrightness: 0.44)
    private static let directorColor = Color.tone(
        hue: 250 / 360,
        saturation: 0.45,
        brightness: 0.90,
        lightBrightness: 0.48
    )
    private static let creditedArtistsColor = Color.tone(
        hue: 340 / 360,
        saturation: 0.50,
        brightness: 0.84,
        lightBrightness: 0.46
    )

    var color: Color {
        switch self {
        case .featuring: Self.featuringColor
        case .producers: Self.producersColor
        case .collaboration: Self.collaborationColor
        case .refs: Self.refsColor
        case .director: Self.directorColor
        // Shares the director tone: both are technical credits with no page of their own.
        case .engineer: Self.directorColor
        case .creditedArtists: Self.creditedArtistsColor
        }
    }

    var label: String {
        switch self {
        case .featuring: "feat."
        case .producers: "prod."
        case .collaboration: "with"
        case .refs: "ref."
        case .director: "dir."
        case .engineer: "eng."
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
        case .engineer: "Engineered by"
        case .creditedArtists: "Artist"
        }
    }
}
