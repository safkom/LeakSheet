import Foundation

nonisolated enum MusicBrainzParsing {
    private struct Response: Decodable {
        struct Artist: Decodable {
            struct Alias: Decodable { let name: String }
            let name: String
            let score: Int?
            let aliases: [Alias]?
        }
        let artists: [Artist]
    }

    /// Other names of the artist `name` refers to ("Ye" for "Kanye West"), empty when MusicBrainz
    /// has no confident match. A hit needs a high score and `name` as its name or an alias.
    static func aliases(from data: Data, for name: String) -> [String] {
        guard let response = try? JSONDecoder().decode(Response.self, from: data) else { return [] }
        let want = LibraryMatcher.normalize(name)
        for artist in response.artists where (artist.score ?? 0) >= 95 {
            let names = [artist.name] + (artist.aliases ?? []).map(\.name)
            guard names.contains(where: { LibraryMatcher.normalize($0) == want }) else { continue }
            return names.filter { LibraryMatcher.normalize($0) != want }
        }
        return []
    }
}

/// Artist aliases from MusicBrainz, asked by the device itself so library names never reach our backend.
actor ArtistAliasService {
    static let shared = ArtistAliasService()

    /// MusicBrainz allows about one request a second.
    private static let spacing: TimeInterval = 1.1
    private var known: [String: [String]]?
    private var lastRequest = Date.distantPast

    /// Aliases for each name, skipping names that failed to load. Answers are cached on disk, misses included.
    /// shortcut: cached forever, an artist's aliases rarely change; add an expiry if one ever does.
    func aliases(for names: [String]) async -> [String: [String]] {
        var cache = known ?? Self.load()
        var out: [String: [String]] = [:]
        for name in names {
            if let hit = cache[name] {
                out[name] = hit
            } else if !Task.isCancelled, let fetched = await fetch(name) {
                cache[name] = fetched
                out[name] = fetched
            } else {
                break
            }
        }
        known = cache
        Self.save(cache)
        return out
    }

    private func fetch(_ name: String) async -> [String]? {
        let wait = Self.spacing - Date().timeIntervalSince(lastRequest)
        if wait > 0 { try? await Task.sleep(for: .seconds(wait)) }
        lastRequest = Date()
        let phrase = name.replacingOccurrences(of: "\"", with: " ").replacingOccurrences(of: "\\", with: " ")
        var components = URLComponents(string: "https://musicbrainz.org/ws/2/artist")
        components?.queryItems = [
            URLQueryItem(name: "query", value: "artist:\"\(phrase)\""),
            URLQueryItem(name: "fmt", value: "json"),
            URLQueryItem(name: "limit", value: "3"),
        ]
        guard let url = components?.url else { return nil }
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.setValue("LeakSheet (https://github.com/safkom/LeakSheet)", forHTTPHeaderField: "User-Agent")
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200
        else { return nil }
        return MusicBrainzParsing.aliases(from: data, for: name)
    }

    private static var file: URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent("musicbrainz-aliases.json")
    }

    private static func load() -> [String: [String]] {
        guard let file, let data = try? Data(contentsOf: file) else { return [:] }
        return (try? JSONDecoder().decode([String: [String]].self, from: data)) ?? [:]
    }

    private static func save(_ cache: [String: [String]]) {
        guard let file, let data = try? JSONEncoder().encode(cache) else { return }
        try? data.write(to: file, options: .atomic)
    }
}
