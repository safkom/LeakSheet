import Foundation

/// Canonicalizes tracker URLs so variants of the same tracker compare equal
/// (edit vs htmlview, gid fragments, share query params, scheme/host case).
/// Mirrors the backend's `_normalize_url`: for Google Sheets the spreadsheet
/// ID is the identity and the canonical form is `/htmlview`; for other hosts
/// the bare host canonicalizes to a trailing slash.
nonisolated enum TrackerURLNormalizer {
    static func normalize(_ raw: String) -> String {
        var input = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !input.isEmpty else { return input }

        let lower = input.lowercased()
        if !lower.hasPrefix("http://") && !lower.hasPrefix("https://") {
            input = "https://" + input
        }

        if let id = sheetID(in: input) {
            return "https://docs.google.com/spreadsheets/d/\(id)/htmlview"
        }

        guard var components = URLComponents(string: input), let host = components.host else {
            return input
        }
        components.scheme = components.scheme?.lowercased()
        components.host = host.lowercased()
        components.fragment = nil
        if components.path.isEmpty && components.query == nil {
            components.path = "/"
        }
        return components.url?.absoluteString ?? input
    }

    // Mirrors backend SHEET_ID_PATTERN:
    // docs\.google\.com/spreadsheets(?:/u/\d+)?/d/([A-Za-z0-9_-]+)
    private static func sheetID(in url: String) -> String? {
        let pattern = /docs\.google\.com\/spreadsheets(?:\/u\/\d+)?\/d\/([A-Za-z0-9_-]+)/
            .ignoresCase()
        guard let match = url.firstMatch(of: pattern) else { return nil }
        return String(match.output.1)
    }
}
