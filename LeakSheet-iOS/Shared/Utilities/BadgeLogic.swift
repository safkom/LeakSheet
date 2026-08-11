import Foundation

/// SPEC §12 "Display Logic" — badge dedupe rules shared with the web app
/// (`useUtils.effectiveBadge` / `getAvailBadge`): one primary pill, plus an
/// availability pill only when it adds information beyond the quality.
nonisolated enum BadgeLogic {
    struct Pill: Equatable {
        let text: String
        /// Style via `qualityVariant` when true, `availabilityVariant` when false.
        let isQuality: Bool
    }

    /// Availability values that add information beyond a shown quality pill.
    /// Mirrors the web's `_AVAILABILITY_VALUES` gate set.
    static let informativeAvailability: Set<String> = [
        "og file", "og files", "full", "tagged", "stem", "stem bounce",
        "stem bounces", "beat only", "partial", "snippet", "confirmed",
        "unavailable",
    ]

    private static func norm(_ s: String?) -> String {
        (s ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private static func trimmed(_ s: String?) -> String {
        (s ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The primary pill: quality — unless quality is empty / "Not Available" /
    /// "N/A", in which case availability stands in (styled as availability).
    /// Nil when neither carries information.
    static func primaryPill(quality: String?, availability: String?) -> Pill? {
        let q = norm(quality)
        let a = norm(availability)
        if q.isEmpty || q == "not available" || q == "n/a" {
            guard !a.isEmpty, a != "n/a" else { return nil }
            return Pill(text: trimmed(availability), isQuality: false)
        }
        return Pill(text: trimmed(quality), isQuality: true)
    }

    /// The secondary availability pill — only when a quality pill is showing,
    /// availability differs from it, and the value is in the informative
    /// whitelist. Nil suppresses the pill.
    static func availabilityPill(quality: String?, availability: String?) -> Pill? {
        let a = norm(availability)
        guard !a.isEmpty, a != "n/a", a != "not available" else { return nil }
        let q = norm(quality)
        guard !q.isEmpty, q != "not available", q != "n/a" else { return nil }
        guard a != q, informativeAvailability.contains(a) else { return nil }
        return Pill(text: trimmed(availability), isQuality: false)
    }
}

// MARK: - Glossary

/// The vocabulary a tracker uses ("Stem Bounce", "OG File", …), shared so the
/// iOS legend sheet and the tvOS one can't drift. They had: tvOS listed "Best
/// of" twice under two emoji — which also collided its ForEach ids, since it
/// keys on the description — and omitted every quality term.
extension BadgeLogic {
    struct Term: Identifiable, Sendable {
        let name: String
        let detail: String
        var id: String { name }
    }

    /// Carries the `Badge` so callers render its own emoji and label rather
    /// than retyping either.
    struct BadgeTerm: Identifiable, Sendable {
        let badge: Badge
        let detail: String
        var name: String { badge.label }
        var emoji: String { badge.emoji }
        var id: String { badge.rawValue }
    }

    static let qualityGlossary: [Term] = [
        .init(name: "Lossless", detail: "Uncompressed studio quality (FLAC/WAV)."),
        .init(name: "CD Quality", detail: "Lossy but high-fidelity, ~320 kbps."),
        .init(name: "High Quality", detail: "Good lossy quality."),
        .init(name: "Recording", detail: "Captured from a playback, not a source file."),
        .init(name: "Low Quality", detail: "Compressed or degraded audio."),
        .init(name: "Not Available", detail: "No file is circulating."),
    ]

    static let availabilityGlossary: [Term] = [
        .init(name: "OG File", detail: "The original leaked file, untouched."),
        .init(name: "Full", detail: "The complete track is out."),
        .init(name: "Tagged", detail: "Full, but watermarked with producer/DJ tags."),
        .init(name: "Partial", detail: "Only part of the track circulates."),
        .init(name: "Snippet", detail: "A short clip only."),
        .init(name: "Stem Bounce", detail: "Rendered from the individual track stems."),
        .init(name: "Beat Only", detail: "Instrumental / beat, no vocals."),
        .init(name: "Confirmed", detail: "Known to exist, but not circulating."),
        .init(name: "Rumored", detail: "Reported to exist — unverified."),
        .init(name: "Conflicting Sources", detail: "Sources disagree on the details."),
        .init(name: "Unavailable", detail: "Not obtainable."),
    ]

    static let badgeGlossary: [BadgeTerm] = [
        .init(badge: .best, detail: "A standout track."),
        .init(badge: .special, detail: "Notable or highlighted."),
        .init(badge: .grail, detail: "A highly sought-after holy grail."),
        .init(badge: .wanted, detail: "Actively wanted by the community."),
        .init(badge: .worst, detail: "Widely disliked."),
        .init(badge: .ai, detail: "AI-generated — not an authentic leak."),
    ]
}
