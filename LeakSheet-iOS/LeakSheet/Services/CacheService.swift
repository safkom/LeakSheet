import Foundation

/// Disk-based cache for parsed tracker data with ETag validation.
actor CacheService {
    static let shared = CacheService()

    private let cacheDirectory: URL

    struct CachedEntry: Codable, Sendable {
        let data: Data
        let etag: String
        let timestamp: Date
        let artistName: String
        let slug: String
        let totalSongs: Int
        let totalVersions: Int
        var version: Int = 1
    }

    private static let currentVersion = 1
    /// Age after which a cached entry is treated as stale and discarded on read.
    private static let maxAge: TimeInterval = 7 * 24 * 3600

    private init() {
        cacheDirectory = URL.cachesDirectory.appending(path: "LeakSheet", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
    }

    private func cacheFile(for url: String) -> URL {
        let hash = Data(url.utf8).base64EncodedString()
            .replacing("/", with: "_")
            .prefix(64)
        return cacheDirectory.appending(path: "tracker_\(hash).json")
    }

    func getCachedTracker(for url: String) -> CachedEntry? {
        let file = cacheFile(for: url)
        guard let data = try? Data(contentsOf: file) else { return nil }
        guard let entry = try? JSONDecoder().decode(CachedEntry.self, from: data) else { return nil }
        guard entry.version == Self.currentVersion else {
            // Schema version mismatch — discard stale cache entry
            try? FileManager.default.removeItem(at: file)
            return nil
        }
        if Date.now.timeIntervalSince(entry.timestamp) > Self.maxAge {
            try? FileManager.default.removeItem(at: file)
            return nil
        }
        return entry
    }

    func getCachedArtist(for url: String) -> Artist? {
        guard let entry = getCachedTracker(for: url) else { return nil }
        return Self.decodeArtist(from: entry.data)
    }

    // nonisolated to avoid main-actor-isolated Codable conformance warnings
    private nonisolated static func decodeArtist(from data: Data) -> Artist? {
        try? JSONDecoder().decode(Artist.self, from: data)
    }

    private nonisolated static func encodeArtist(_ artist: Artist) -> Data? {
        try? JSONEncoder().encode(artist)
    }

    func getCachedEtag(for url: String) -> String? {
        getCachedTracker(for: url)?.etag
    }

    func cacheTracker(url: String, artist: Artist, etag: String, totalSongs: Int, totalVersions: Int) {
        guard let artistData = Self.encodeArtist(artist) else { return }
        let entry = CachedEntry(
            data: artistData,
            etag: etag,
            timestamp: .now,
            artistName: artist.name,
            slug: artist.slug,
            totalSongs: totalSongs,
            totalVersions: totalVersions
        )
        guard let entryData = try? JSONEncoder().encode(entry) else { return }
        let file = cacheFile(for: url)
        try? entryData.write(to: file, options: .atomic)
    }

    func clearCache() {
        let files = (try? FileManager.default.contentsOfDirectory(
            at: cacheDirectory,
            includingPropertiesForKeys: nil
        )) ?? []
        for file in files where file.lastPathComponent.hasPrefix("tracker_") {
            try? FileManager.default.removeItem(at: file)
        }
    }
}
