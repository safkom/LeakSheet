import Foundation
import Testing

@testable import LeakSheet

/// CacheService v2: raw response bytes, full SHA-256 keys, version-gated
/// entries, orphan sweep of v1-era files, and size reporting.
struct CacheServiceTests {
    private func makeService() -> (CacheService, URL) {
        let dir = FileManager.default.temporaryDirectory
            .appending(path: "CacheServiceTests-\(UUID().uuidString)")
        return (CacheService(directory: dir), dir)
    }

    private let artistJSON = Data(#"{"name": "Test", "slug": "test", "eras": []}"#.utf8)

    @Test func `round trip stores raw bytes and etag`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        await service.cacheTracker(url: "https://example.com/sheet", data: artistJSON, etag: "abc123")
        let entry = try #require(await service.getCachedTracker(for: "https://example.com/sheet"))
        #expect(entry.data == artistJSON)
        #expect(entry.etag == "abc123")

        let artist = try #require(await service.getCachedArtist(for: "https://example.com/sheet"))
        #expect(artist.slug == "test")
    }

    @Test func `long urls sharing a prefix do not collide`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        // The v1 key was base64(url) truncated to 64 chars — these two URLs
        // share their first 48+ bytes and collided under that scheme.
        let base = "https://docs.google.com/spreadsheets/d/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/edit?gid="
        let urlA = base + "111"
        let urlB = base + "222"

        await service.cacheTracker(url: urlA, data: Data(#"{"name": "A", "slug": "a", "eras": []}"#.utf8), etag: "a")
        await service.cacheTracker(url: urlB, data: Data(#"{"name": "B", "slug": "b", "eras": []}"#.utf8), etag: "b")

        let a = try #require(await service.getCachedArtist(for: urlA))
        let b = try #require(await service.getCachedArtist(for: urlB))
        #expect(a.slug == "a")
        #expect(b.slug == "b")
    }

    @Test func `version mismatch discards entry`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        await service.cacheTracker(url: "https://example.com/x", data: artistJSON, etag: "e")
        let file = await service.cacheFileForTesting(url: "https://example.com/x")
        let meta = await service.metaFileForTesting(url: "https://example.com/x")

        // The schema version lives in the sidecar since v3 — the payload is
        // raw response bytes with nothing of ours in them.
        var raw = try JSONSerialization.jsonObject(with: Data(contentsOf: meta)) as! [String: Any]
        raw["version"] = 2
        try JSONSerialization.data(withJSONObject: raw).write(to: meta)

        #expect(await service.getCachedTracker(for: "https://example.com/x") == nil)
        #expect(!FileManager.default.fileExists(atPath: file.path))
        #expect(!FileManager.default.fileExists(atPath: meta.path))
    }

    @Test func `v1 orphan files are swept on init`() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appending(path: "CacheServiceTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        // v1 filenames were base64-derived (may contain =, +, uppercase)
        let orphan = dir.appending(path: "tracker_aHR0cHM6Ly9leGFtcGxlLmNvbQ==.json")
        try Data("{}".utf8).write(to: orphan)

        let service = CacheService(directory: dir)
        await service.sweepLegacyEntries()
        #expect(!FileManager.default.fileExists(atPath: orphan.path))
    }

    @Test func `cache size reflects stored entries and clears`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        #expect(await service.cacheSizeBytes() == 0)
        await service.cacheTracker(url: "https://example.com/y", data: artistJSON, etag: "e")
        #expect(await service.cacheSizeBytes() > 0)
        await service.clearCache()
        #expect(await service.cacheSizeBytes() == 0)
    }

    @Test func `etag lookup`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        await service.cacheTracker(url: "https://example.com/z", data: artistJSON, etag: "W/xyz")
        #expect(await service.getCachedEtag(for: "https://example.com/z") == "W/xyz")
        #expect(await service.getCachedEtag(for: "https://example.com/missing") == nil)
    }

    // MARK: - Metadata sidecar
    //
    // Reading one ETag used to cost a full Data(contentsOf:) + JSONDecoder
    // pass over a multi-MB base64'd payload, on every tracker load, before the
    // conditional request was even sent — and the data-age chip paid it again
    // after the screen was already up, which is what shunted the list down
    // mid-scroll.

    @Test func `caching writes a sidecar alongside the payload`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        let url = "https://example.com/meta"
        await service.cacheTracker(url: url, data: artistJSON, etag: "sidecar-etag")

        let metaPath = await service.metaFileForTesting(url: url)
        #expect(FileManager.default.fileExists(atPath: metaPath.path))
        // Sidecar must stay tiny — that is the entire point.
        let size = try #require(try metaPath.resourceValues(forKeys: [.fileSizeKey]).fileSize)
        #expect(size < 512)

        let meta = try #require(await service.getCachedMeta(for: url))
        #expect(meta.etag == "sidecar-etag")
    }

    @Test func `the sidecar is read without touching the payload`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        let url = "https://example.com/detached"
        await service.cacheTracker(url: url, data: artistJSON, etag: "e1")
        // Corrupt the payload. A sidecar read must not care.
        try Data("not json at all".utf8).write(to: await service.cacheFileForTesting(url: url))

        #expect(await service.getCachedEtag(for: url) == "e1")
    }

    @Test func `an entry with no sidecar is discarded, not trusted`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        let url = "https://example.com/legacy"
        await service.cacheTracker(url: url, data: artistJSON, etag: "old")
        // A v2 envelope, or a write interrupted between the two files. Since v3
        // the payload is raw bytes carrying no etag, timestamp or version, so a
        // sidecar-less payload cannot be validated and must not be served.
        try FileManager.default.removeItem(at: await service.metaFileForTesting(url: url))

        #expect(await service.getCachedEtag(for: url) == nil)
        #expect(await service.getCachedTracker(for: url) == nil)
        #expect(!FileManager.default.fileExists(atPath: await service.cacheFileForTesting(url: url).path))
    }

    @Test func `the payload file is the raw response, not a JSON envelope`() async throws {
        // v2 wrapped the bytes in a CachedEntry, and JSONEncoder base64s Data —
        // a third larger on disk plus an encode/decode pass over a multi-MB
        // tracker on the coldest path in the app.
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        await service.cacheTracker(url: "https://example.com/raw", data: artistJSON, etag: "e")
        let onDisk = try Data(contentsOf: await service.cacheFileForTesting(url: "https://example.com/raw"))
        #expect(onDisk == artistJSON)
    }

    @Test func `a sidecar without its payload is not treated as a valid cache`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        let url = "https://example.com/orphan-meta"
        await service.cacheTracker(url: url, data: artistJSON, etag: "e")
        try FileManager.default.removeItem(at: await service.cacheFileForTesting(url: url))

        // Returning the ETag here would make the loader send a conditional
        // request, take the 304, and find nothing to replay.
        #expect(await service.getCachedMeta(for: url) == nil)
    }

    @Test func `removing an entry removes its sidecar`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        let url = "https://example.com/gone"
        await service.cacheTracker(url: url, data: artistJSON, etag: "e")
        await service.removeTracker(for: url)

        #expect(!FileManager.default.fileExists(atPath: await service.metaFileForTesting(url: url).path))
        #expect(await service.getCachedMeta(for: url) == nil)
    }

    /// The legacy sweep deletes anything under "tracker_" whose stem isn't 64
    /// hex chars. Sidecars are "tracker_<hex>_meta.json", so an unguarded
    /// sweep wipes every one of them on launch.
    @Test func `the legacy sweep spares sidecars`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        let url = "https://example.com/swept"
        await service.cacheTracker(url: url, data: artistJSON, etag: "e")
        await service.sweepLegacyEntries()

        #expect(FileManager.default.fileExists(atPath: await service.metaFileForTesting(url: url).path))
        #expect(await service.getCachedEtag(for: url) == "e")
    }

    @Test func `clearing the cache removes sidecars too`() async throws {
        let (service, dir) = makeService()
        defer { try? FileManager.default.removeItem(at: dir) }

        await service.cacheTracker(url: "https://example.com/c1", data: artistJSON, etag: "e")
        await service.clearCache()
        #expect(await service.cacheSizeBytes() == 0)
        #expect(await service.getCachedMeta(for: "https://example.com/c1") == nil)
    }
}
