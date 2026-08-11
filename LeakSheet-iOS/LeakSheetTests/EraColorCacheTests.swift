import Testing

@testable import LeakSheet

/// Pins the era-colour cache eviction.
///
/// The bug this exists for: `init` restored `cache` from UserDefaults (up to
/// 200 entries) but left `insertionOrder` empty. On any launch where the
/// persisted cache was already full, the first extraction pushed the count to
/// 201, computed `excess == 1`, and evicted `insertionOrder.prefix(1)` — the
/// key that had just been added. The cache froze at whatever 200 entries were
/// on disk and no new era colour was ever written again for the life of the
/// install.
@Suite("Era colour cache eviction")
struct EraColorCacheTests {
    private func makeCache(_ count: Int, prefix: String = "k") -> ([String: [Double]], [String]) {
        var cache: [String: [Double]] = [:]
        var order: [String] = []
        for i in 0..<count {
            let key = "\(prefix)\(i)"
            cache[key] = [0.1, 0.2, 0.3]
            order.append(key)
        }
        return (cache, order)
    }

    @Test func `under the limit nothing is evicted`() {
        var (cache, order) = makeCache(EraColorExtractor.cacheLimit)
        EraColorExtractor.evict(cache: &cache, insertionOrder: &order)
        #expect(cache.count == EraColorExtractor.cacheLimit)
        #expect(order.count == EraColorExtractor.cacheLimit)
    }

    @Test func `the newest entry survives when the cache overflows`() {
        var (cache, order) = makeCache(EraColorExtractor.cacheLimit)
        cache["fresh"] = [0.9, 0.9, 0.9]
        order.append("fresh")

        EraColorExtractor.evict(cache: &cache, insertionOrder: &order)

        // The whole bug: "fresh" used to be the one thing dropped.
        #expect(cache["fresh"] != nil)
        #expect(cache["k0"] == nil, "oldest entry should go first")
        #expect(cache.count == EraColorExtractor.cacheLimit)
        #expect(order.first == "k1")
    }

    @Test func `eviction drops oldest-first across several overflows`() {
        var (cache, order) = makeCache(EraColorExtractor.cacheLimit)
        for i in 0..<5 {
            cache["new\(i)"] = [0.5, 0.5, 0.5]
            order.append("new\(i)")
            EraColorExtractor.evict(cache: &cache, insertionOrder: &order)
        }
        #expect(cache.count == EraColorExtractor.cacheLimit)
        for i in 0..<5 {
            #expect(cache["k\(i)"] == nil, "k\(i) was among the five oldest")
            #expect(cache["new\(i)"] != nil, "new\(i) was just written")
        }
    }

    /// `insertionOrder` shorter than `cache` is reachable: it is seeded from
    /// the restored keys, but an oversized persisted dictionary still has to
    /// drain. Unclamped, `removeFirst(excess)` traps here.
    @Test func `an insertion order shorter than the cache does not trap`() {
        var (cache, _) = makeCache(EraColorExtractor.cacheLimit + 50)
        var order: [String] = ["k0"]
        EraColorExtractor.evict(cache: &cache, insertionOrder: &order)
        #expect(cache["k0"] == nil)
        #expect(order.isEmpty)
        // Only what the order could name was dropped; the rest drains later.
        #expect(cache.count == EraColorExtractor.cacheLimit + 49)
    }

    @Test func `an empty insertion order against a full cache is a no-op, not a crash`() {
        var (cache, _) = makeCache(EraColorExtractor.cacheLimit + 1)
        var order: [String] = []
        EraColorExtractor.evict(cache: &cache, insertionOrder: &order)
        #expect(cache.count == EraColorExtractor.cacheLimit + 1)
    }
}
