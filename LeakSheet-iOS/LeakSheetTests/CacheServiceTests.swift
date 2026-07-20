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

        // Rewrite the entry as an older schema version
        var raw = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
        raw["version"] = 1
        try JSONSerialization.data(withJSONObject: raw).write(to: file)

        #expect(await service.getCachedTracker(for: "https://example.com/x") == nil)
        #expect(!FileManager.default.fileExists(atPath: file.path))
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
}
