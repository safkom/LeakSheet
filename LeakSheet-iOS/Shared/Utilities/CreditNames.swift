import Foundation

/// Splits a credit field ("Producers", "Featuring") into individual artist names.
nonisolated enum CreditNames {
    /// Removed case-insensitively from the start of each part; longer ones first.
    private static let prefixes = ["prod. by", "prod.", "feat.", "ft."]
    private static let placeholder = "???"

    static func split(_ raw: String?) -> [String] {
        guard let raw, !raw.isEmpty else { return [] }
        // shortcut: a comma inside a name ("Tyler, The Creator") splits it; upgrade with a
        // known-names list if users hit it.
        var parts = raw.split(whereSeparator: { ",&+/;".contains($0) }).map(String.init)
        for word in [" x ", " and "] {
            parts = parts.flatMap { splitOn($0, separator: word) }
        }
        return parts.compactMap { part in
            let name = stripPrefixes(part)
            return name.isEmpty || name == placeholder ? nil : name
        }
    }

    /// Identity of a name for indexing: case and punctuation don't count.
    static func key(_ name: String) -> String {
        Song.nameKey(name)
    }

    private static func splitOn(_ text: String, separator: String) -> [String] {
        var out: [String] = []
        var rest = Substring(text)
        while let range = rest.range(of: separator, options: .caseInsensitive) {
            out.append(String(rest[..<range.lowerBound]))
            rest = rest[range.upperBound...]
        }
        out.append(String(rest))
        return out
    }

    private static func stripPrefixes(_ part: String) -> String {
        var name = part.trimmingCharacters(in: .whitespacesAndNewlines)
        var stripped = true
        while stripped {
            stripped = false
            for prefix in prefixes {
                if let range = name.range(of: prefix, options: [.anchored, .caseInsensitive]) {
                    name = String(name[range.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
                    stripped = true
                }
            }
        }
        return name
    }
}
