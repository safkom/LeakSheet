import CryptoKit
import Foundation

/// Disk-based cache for tracker payloads with ETag validation.
///
/// The payload file IS the raw response bytes: no envelope (JSONEncoder would base64
/// them) and no re-encode, so new API fields survive. Keyed by the SHA-256 of the
/// normalized URL; ETag, timestamp and version live in a small sidecar.
actor CacheService {
    static let shared = CacheService()

    private let cacheDirectory: URL

    struct CachedEntry: Codable, Sendable {
        let data: Data
        let etag: String
        let timestamp: Date
        var version: Int = CacheService.currentVersion
    }

    private static let currentVersion = 3
    /// Entries untouched this long are deleted by the launch sweep. Age never
    /// invalidates a read: an old copy is still the offline fallback, and its
    /// ETag still earns a 304 when the tracker hasn't changed.
    private static let maxAge: TimeInterval = 30 * 24 * 3600

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

    /// Keyed on the normalized URL, so "yetracker.net" and "https://yetracker.net/"
    /// share one entry and ETag.
    private func digest(for url: String) -> String {
        let key = TrackerURLNormalizer.normalize(url)
        return SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func cacheFile(for url: String) -> URL {
        cacheDirectory.appending(path: "tracker_\(digest(for: url)).json")
    }

    /// Sidecar holding `CachedMeta`, so reading an ETag is a ~100-byte read rather
    /// than a decode of the multi-MB payload.
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
        // The sidecar is authoritative: none means a v2 envelope or a half-written pair,
        // and either way the bytes cannot be validated. Both files go.
        guard let meta = readMeta(for: url), meta.version == Self.currentVersion else {
            removeTracker(for: url)
            return nil
        }
        guard let data = try? Data(contentsOf: cacheFile(for: url)) else { return nil }
        return CachedEntry(data: data, etag: meta.etag, timestamp: meta.timestamp, version: meta.version)
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
    /// Returns nil if the payload itself is missing or stale — the two files
    /// are only ever written together, but a partial cache directory must not
    /// make the loader think it has a valid ETag.
    func getCachedMeta(for url: String) -> CachedMeta? {
        guard let meta = readMeta(for: url),
              meta.version == Self.currentVersion,
              FileManager.default.fileExists(atPath: cacheFile(for: url).path)
        else { return nil }
        return meta
    }

    private func readMeta(for url: String) -> CachedMeta? {
        guard let data = try? Data(contentsOf: metaFile(for: url)) else { return nil }
        return try? JSONDecoder().decode(CachedMeta.self, from: data)
    }

    func getCachedEtag(for url: String) -> String? {
        getCachedMeta(for: url)?.etag
    }

    /// Store the raw server response bytes for a tracker URL.
    ///
    /// The payload is written verbatim — no envelope, no encode pass. The
    /// sidecar goes out second: a payload without a sidecar reads as a miss,
    /// which is the safe way round for an interrupted write.
    func cacheTracker(url: String, data: Data, etag: String) {
        let timestamp = Date.now
        do {
            try data.write(to: cacheFile(for: url), options: .atomic)
        } catch {
            return
        }
        writeMeta(CachedMeta(etag: etag, timestamp: timestamp), for: url)
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

    /// Remove entries untouched for `maxAge`, and v1-era files whose
    /// base64-derived names don't match the SHA-256 hex scheme.
    /// Runs detached from `init`; exposed for tests to invoke deterministically.
    func sweepLegacyEntries() {
        Self.sweepLegacyFiles(in: cacheDirectory)
    }

    private nonisolated static func sweepLegacyFiles(in directory: URL) {
        let files = (try? FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.contentModificationDateKey]
        )) ?? []
        for file in files where file.lastPathComponent.hasPrefix("tracker_") {
            let modified = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
            if let modified, Date.now.timeIntervalSince(modified) > maxAge {
                try? FileManager.default.removeItem(at: file)
                continue
            }
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
