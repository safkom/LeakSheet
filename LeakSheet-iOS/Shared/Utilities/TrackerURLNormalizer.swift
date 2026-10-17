import Foundation

/// Canonicalizes tracker URLs so variants of one tracker compare equal, as the backend's
/// `_normalize_url` does: see DECISIONS.md::TrackerURLNormalizer.swift::mirrors-backend
nonisolated enum TrackerURLNormalizer {
    static func normalize(_ raw: String) -> String {
        var input = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !input.isEmpty else { return input }

        let lower = input.lowercased()
        if !lower.hasPrefix("http://") && !lower.hasPrefix("https://") {
            input = "https://" + input
        }

        guard var components = URLComponents(string: input), let host = components.host?.lowercased() else {
            return input
        }
        let scheme = (components.scheme ?? "https").lowercased()

        if host == "docs.google.com", let id = sheetID(inPath: components.percentEncodedPath) {
            return "https://docs.google.com/spreadsheets/d/\(id)/htmlview"
        }

        components.scheme = scheme
        components.host = host
        components.user = nil
        components.password = nil
        if components.port == (scheme == "https" ? 443 : 80) { components.port = nil }
        components.fragment = nil
        if components.path.isEmpty && components.query == nil {
            components.path = "/"
        }
        return components.url?.absoluteString ?? input
    }

    // Mirrors backend SHEET_ID_PATTERN, searched in "docs.google.com" + path:
    // docs\.google\.com/spreadsheets(?:/u/\d+)?/d/([A-Za-z0-9_-]+)
    private static func sheetID(inPath path: String) -> String? {
        let pattern = /docs\.google\.com\/spreadsheets(?:\/u\/\d+)?\/d\/([A-Za-z0-9_-]+)/
        guard let match = ("docs.google.com" + path).firstMatch(of: pattern) else { return nil }
        return String(match.output.1)
    }
}
