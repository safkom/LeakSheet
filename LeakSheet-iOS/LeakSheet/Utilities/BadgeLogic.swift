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
