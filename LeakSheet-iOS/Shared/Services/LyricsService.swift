import Foundation

nonisolated struct LyricLine: Equatable, Sendable {
    let time: TimeInterval
    let text: String
}

nonisolated struct Lyrics: Equatable, Sendable {
    let plain: String?
    let synced: [LyricLine]

    static let none = Lyrics(plain: nil, synced: [])
    var isEmpty: Bool { synced.isEmpty && (plain ?? "").isEmpty }

    /// The line sung at `time`: the last one that has started.
    func currentIndex(at time: TimeInterval) -> Int? {
        synced.lastIndex { $0.time <= time }
    }
}

nonisolated enum LyricsParsing {
    /// Tracker names carry tags like "[V2]" or "(OG)" that no lyrics index has.
    static func searchTitle(_ name: String) -> String {
        var out = ""
        var depth = 0
        for c in name {
            switch c {
            case "(", "[": depth += 1
            case ")", "]": depth = max(0, depth - 1)
            default: if depth == 0 { out.append(c) }
            }
        }
        let title = out.trimmingCharacters(in: .whitespaces)
        return title.isEmpty ? name : title
    }

    /// LRC text to timed lines. Lines may carry several stamps; metadata tags like `[ar:x]` are skipped.
    static func parseLRC(_ lrc: String) -> [LyricLine] {
        var lines: [LyricLine] = []
        for raw in lrc.split(whereSeparator: \.isNewline) {
            var rest = Substring(raw)
            var stamps: [TimeInterval] = []
            while rest.first == "[", let close = rest.firstIndex(of: "]"),
                  let time = timestamp(rest[rest.index(after: rest.startIndex)..<close]) {
                stamps.append(time)
                rest = rest[rest.index(after: close)...]
            }
            let text = rest.trimmingCharacters(in: .whitespaces)
            lines += stamps.map { LyricLine(time: $0, text: text) }
        }
        return lines.sorted { $0.time < $1.time }
    }

    private static func timestamp(_ tag: Substring) -> TimeInterval? {
        let parts = tag.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, let min = Double(parts[0]), let sec = Double(parts[1]) else { return nil }
        return min * 60 + sec
    }

    struct Hit: Decodable, Sendable {
        let trackName: String?
        let duration: Double?
        let plainLyrics: String?
        let syncedLyrics: String?
    }

    /// Synced lyrics from a different cut drift out of time; past this gap only plain text is safe.
    static let maxSyncDrift: TimeInterval = 15

    /// Best hit whose title equals `title`, preferring synced text and the closest length.
    static func pick(_ hits: [Hit], title: String, duration: TimeInterval?) -> Lyrics {
        let want = LibraryMatcher.normalize(title)
        let usable = hits.filter {
            LibraryMatcher.normalize($0.trackName ?? "") == want
                && !(($0.syncedLyrics ?? "").isEmpty && ($0.plainLyrics ?? "").isEmpty)
        }
        func gap(_ hit: Hit) -> Double {
            guard let duration, duration > 0, let d = hit.duration else { return 0 }
            return abs(d - duration)
        }
        guard let hit = usable.min(by: {
            let (a, b) = (($0.syncedLyrics ?? "").isEmpty ? 1 : 0, ($1.syncedLyrics ?? "").isEmpty ? 1 : 0)
            return (a, gap($0)) < (b, gap($1))
        }) else { return .none }
        let synced = gap(hit) <= maxSyncDrift ? parseLRC(hit.syncedLyrics ?? "") : []
        let plain = (hit.plainLyrics ?? "").isEmpty ? nil : hit.plainLyrics
        return Lyrics(plain: plain, synced: synced)
    }
}

/// Lyrics from LRCLIB (community-run, no key). Unreleased songs often have none: `.none` is a normal answer.
actor LyricsService {
    static let shared = LyricsService()
    private var cache: [String: Lyrics] = [:]

    /// Nil on a network failure (not cached, so a retry can succeed).
    func lyrics(artist: String, title: String, duration: TimeInterval?) async -> Lyrics? {
        let key = LibraryMatcher.normalize(artist) + "|" + LibraryMatcher.normalize(title)
        if let hit = cache[key] { return hit }
        var components = URLComponents(string: "https://lrclib.net/api/search")
        components?.queryItems = [
            URLQueryItem(name: "track_name", value: title),
            URLQueryItem(name: "artist_name", value: artist),
        ]
        guard let url = components?.url else { return nil }
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.setValue("LeakSheet (https://github.com/safkom/LeakSheet)", forHTTPHeaderField: "User-Agent")
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let hits = try? JSONDecoder().decode([LyricsParsing.Hit].self, from: data)
        else { return nil }
        let result = LyricsParsing.pick(hits, title: title, duration: duration)
        cache[key] = result
        return result
    }
}
