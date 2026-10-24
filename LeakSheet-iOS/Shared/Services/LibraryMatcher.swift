import Foundation

/// An artist in the user's music library with how often they play it.
nonisolated struct LibraryArtist: Sendable, Equatable {
    let name: String
    let plays: Int
}

/// Matches library artists to discovery trackers by exact normalized name. Fuzzy
/// matching would pair "Drake" with "Drake Bell"; a missed alias costs less than a wrong hit.
nonisolated enum LibraryMatcher {
    /// Lowercased, diacritics and punctuation stripped, leading "the " dropped.
    static func normalize(_ name: String) -> String {
        let folded = name.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
        let key = folded.filter { $0.isLetter || $0.isNumber || $0 == " " }
            .split(separator: " ").joined(separator: " ")
        return key.hasPrefix("the ") ? String(key.dropFirst(4)) : key
    }

    /// A library artistName can be "A & B" or "A, B feat. C": the whole string plus each part.
    /// shortcut: splitting also cuts "Earth, Wind & Fire" into parts, harmless (parts never match).
    static func candidates(_ artistName: String) -> [String] {
        let parts = artistName
            .replacingOccurrences(of: " & ", with: ",")
            .replacingOccurrences(of: " feat. ", with: ",")
            .replacingOccurrences(of: " ft. ", with: ",")
            .replacingOccurrences(of: " x ", with: ",")
            .split(separator: ",").map(String.init)
        return ([artistName] + parts).map(normalize).filter { !$0.isEmpty }
    }

    /// Trackers whose name matches a library artist (or one of its `aliases`, keyed by library
    /// name), most-played artist first.
    static func recommend(
        library: [LibraryArtist], trackers: [DiscoveryArtist], aliases: [String: [String]] = [:]
    ) -> [DiscoveryArtist] {
        var plays: [String: Int] = [:]
        for artist in library {
            let keys = candidates(artist.name) + (aliases[artist.name] ?? []).map(normalize)
            for key in keys where !key.isEmpty { plays[key, default: 0] += artist.plays }
        }
        let hits = trackers.compactMap { tracker -> (DiscoveryArtist, Int)? in
            plays[normalize(tracker.name)].map { (tracker, $0) }
        }
        return hits.sorted { $0.1 > $1.1 }.map(\.0)
    }

    /// The most-played library artists no tracker matches yet: the ones worth an alias lookup.
    static func unmatched(library: [LibraryArtist], trackers: [DiscoveryArtist], limit: Int) -> [LibraryArtist] {
        let trackerKeys = Set(trackers.map { normalize($0.name) })
        return library
            .filter { $0.plays > 0 && trackerKeys.isDisjoint(with: candidates($0.name)) }
            .sorted { $0.plays > $1.plays }
            .prefix(limit).map { $0 }
    }
}
