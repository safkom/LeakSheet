import CryptoKit
import Foundation

/// Disk-based cache for tracker payloads with ETag validation.
///
/// v2 (2026-07-17): stores the raw server response bytes instead of a
/// re-encoded `Artist` (kills a full multi-MB encode pass per load and
/// guarantees cache == server payload, so new optional API fields survive
/// the round-trip), and keys files by the full SHA-256 of the URL — the v1
/// scheme truncated base64(url) to 64 chars, so long URLs sharing a prefix
/// collided.
actor CacheService {
    static let shared = CacheService()

    private let cacheDirectory: URL

    struct CachedEntry: Codable, Sendable {
        let data: Data
        let etag: String
        let timestamp: Date
        var version: Int = CacheService.currentVersion
    }

    private static let currentVersion = 2
    /// Age after which a cached entry is treated as stale and discarded on read.
    private static let maxAge: TimeInterval = 7 * 24 * 3600

    init(directory: URL? = nil) {
        cacheDirectory = directory
            ?? URL.cachesDirectory.appending(path: "LeakSheet", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
        // The `.shared` initializer runs on whichever thread first touches
        // it (usually main) — sweep legacy files off that thread.
        let directoryToSweep = cacheDirectory
        Task.detached(priority: .utility) {
            Self.sweepLegacyFiles(in: directoryToSweep)
        }
    }

    private func cacheFile(for url: String) -> URL {
        let digest = SHA256.hash(data: Data(url.utf8))
        let hex = digest.map { String(format: "%02x", $0) }.joined()
        return cacheDirectory.appending(path: "tracker_\(hex).json")
    }

    /// Test-only accessor for the on-disk location of a URL's entry.
    func cacheFileForTesting(url: String) -> URL {
        cacheFile(for: url)
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

    func getCachedEtag(for url: String) -> String? {
        getCachedTracker(for: url)?.etag
    }

    /// Store the raw server response bytes for a tracker URL.
    func cacheTracker(url: String, data: Data, etag: String) {
        let entry = CachedEntry(data: data, etag: etag, timestamp: .now)
        guard let entryData = try? JSONEncoder().encode(entry) else { return }
        try? entryData.write(to: cacheFile(for: url), options: .atomic)
    }

    func removeTracker(for url: String) {
        try? FileManager.default.removeItem(at: cacheFile(for: url))
    }

    func clearCache() {
        for file in trackerFiles() {
            try? FileManager.default.removeItem(at: file)
        }
    }

    /// Total on-disk size of all cached tracker entries (for Settings).
    func cacheSizeBytes() -> Int64 {
        trackerFiles().reduce(0) { total, file in
            let size = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            return total + Int64(size)
        }
    }

    /// Remove v1-era files whose base64-derived names don't match the SHA-256
    /// hex scheme — they would otherwise sit orphaned until manually cleared.
    /// Runs detached from `init`; exposed for tests to invoke deterministically.
    func sweepLegacyEntries() {
        Self.sweepLegacyFiles(in: cacheDirectory)
    }

    private nonisolated static func sweepLegacyFiles(in directory: URL) {
        let files = (try? FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil
        )) ?? []
        for file in files where file.lastPathComponent.hasPrefix("tracker_") {
            let stem = file.deletingPathExtension().lastPathComponent.dropFirst("tracker_".count)
            let isHexKey = stem.count == 64 && stem.allSatisfy { $0.isHexDigit && !$0.isUppercase }
            if !isHexKey {
                try? FileManager.default.removeItem(at: file)
            }
        }
    }

    private func trackerFiles() -> [URL] {
        let files = (try? FileManager.default.contentsOfDirectory(
            at: cacheDirectory,
            includingPropertiesForKeys: [.fileSizeKey]
        )) ?? []
        return files.filter { $0.lastPathComponent.hasPrefix("tracker_") }
    }
}
