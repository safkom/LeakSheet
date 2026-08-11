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

    /// Just the ETag, timestamp and schema version — everything the load path
    /// needs *before* it knows whether it will use the payload at all.
    struct CachedMeta: Codable, Sendable {
        let etag: String
        let timestamp: Date
        var version: Int = CacheService.currentVersion
    }

    private func digest(for url: String) -> String {
        SHA256.hash(data: Data(url.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func cacheFile(for url: String) -> URL {
        cacheDirectory.appending(path: "tracker_\(digest(for: url)).json")
    }

    /// Sidecar holding `CachedMeta`.
    ///
    /// Exists because reading one ETag used to cost a full multi-MB
    /// `Data(contentsOf:)` + JSONDecoder pass over the base64'd payload — and
    /// that happened on *every* tracker load, before the conditional request
    /// was even sent. The data-age chip paid it a second time. Both now read a
    /// ~100 byte file.
    private func metaFile(for url: String) -> URL {
        cacheDirectory.appending(path: "tracker_\(digest(for: url))_meta.json")
    }

    /// Test-only accessor for the on-disk location of a URL's entry.
    func cacheFileForTesting(url: String) -> URL {
        cacheFile(for: url)
    }

    /// Test-only accessor for the sidecar's location.
    func metaFileForTesting(url: String) -> URL {
        metaFile(for: url)
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

    /// ETag + timestamp without touching the payload.
    ///
    /// Falls back to a full read for entries written before the sidecar
    /// existed, and writes the sidecar on the way out so the next load is
    /// cheap. Returns nil if the payload itself is missing or stale — the two
    /// files are only ever written together, but a partial cache directory
    /// must not make the loader think it has a valid ETag.
    func getCachedMeta(for url: String) -> CachedMeta? {
        if let data = try? Data(contentsOf: metaFile(for: url)),
           let meta = try? JSONDecoder().decode(CachedMeta.self, from: data),
           meta.version == Self.currentVersion,
           Date.now.timeIntervalSince(meta.timestamp) <= Self.maxAge,
           FileManager.default.fileExists(atPath: cacheFile(for: url).path) {
            return meta
        }
        guard let entry = getCachedTracker(for: url) else { return nil }
        let meta = CachedMeta(etag: entry.etag, timestamp: entry.timestamp)
        writeMeta(meta, for: url)
        return meta
    }

    func getCachedEtag(for url: String) -> String? {
        getCachedMeta(for: url)?.etag
    }

    /// Store the raw server response bytes for a tracker URL.
    func cacheTracker(url: String, data: Data, etag: String) {
        let entry = CachedEntry(data: data, etag: etag, timestamp: .now)
        guard let entryData = try? JSONEncoder().encode(entry) else { return }
        try? entryData.write(to: cacheFile(for: url), options: .atomic)
        writeMeta(CachedMeta(etag: etag, timestamp: entry.timestamp), for: url)
    }

    private func writeMeta(_ meta: CachedMeta, for url: String) {
        guard let data = try? JSONEncoder().encode(meta) else { return }
        try? data.write(to: metaFile(for: url), options: .atomic)
    }

    func removeTracker(for url: String) {
        try? FileManager.default.removeItem(at: cacheFile(for: url))
        try? FileManager.default.removeItem(at: metaFile(for: url))
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
            var stem = file.deletingPathExtension().lastPathComponent.dropFirst("tracker_".count)
            // Sidecars are "tracker_<hex>_meta.json" — strip the suffix before
            // the hex check, or this sweep deletes every one of them on launch.
            if stem.hasSuffix("_meta") { stem = stem.dropLast("_meta".count) }
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
