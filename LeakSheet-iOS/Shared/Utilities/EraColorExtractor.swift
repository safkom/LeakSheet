import CoreGraphics
import SwiftUI

/// Extracts the dominant RGB color from an era image — mirrors ColorThief's approach.
/// Returns actual image RGB values so card gradients, text, and borders match the web app exactly.
actor EraColorExtractor {
    static let shared = EraColorExtractor()

    // Cache keyed by art URL not era name — see DECISIONS.md::EraColorExtractor.swift::cache-key
    private var cache: [String: [Double]]
    private static let cacheKey = "leaksheet_era_rgb_v3"
    /// Cache keys oldest-first, so eviction drops the least recently added
    /// rather than an arbitrary slice of `cache.keys`.
    private var insertionOrder: [String] = []
    /// Debounced UserDefaults write (see scheduleFlush).
    private var flushTask: Task<Void, Never>?

    private init() {
        // One-time cleanup of the superseded v2 cache key (v3 re-keyed the
        // cache from era name to art URL); harmless if already absent.
        UserDefaults.standard.removeObject(forKey: "leaksheet_era_rgb_v2")
        cache = UserDefaults.standard.dictionary(forKey: Self.cacheKey) as? [String: [Double]] ?? [:]
        // Seed the eviction order from what we just restored. Without this the
        // list started empty against a full cache, so the first extraction of
        // every launch pushed count to 201 and then evicted
        // insertionOrder.prefix(1) — the key just added. The cache froze at
        // whatever 200 entries were persisted and no new era colour was ever
        // written again. Dictionary order is arbitrary, so restored entries
        // evict in an arbitrary (but stable-for-this-launch) order; entries
        // added during the session still evict oldest-first behind them.
        insertionOrder = Array(cache.keys)
    }

    // MARK: - Public API

    /// Extract from an already-loaded image (no download). Used during prefetch.
    /// `cacheKey` should be the era's raw art URL, unique per image.
    func extractColor(fromImage image: CGImage, cacheKey: String) async -> Color? {
        if let cached = cache[cacheKey] {
            return color(from: cached)
        }
        // Run pixel sampling off the actor so concurrent extractions don't serialize.
        guard let rgb = await Self.dominantRGBOffActor(from: image) else { return nil }
        cache(rgb, forKey: cacheKey)
        return Color(red: rgb.r, green: rgb.g, blue: rgb.b)
    }

    /// Extract from a URL — uses ImageCache to avoid re-downloading. A 128px
    /// thumbnail is plenty: the algorithm samples at ≤100×100 anyway.
    /// `cacheKey` should be the era's raw art URL, unique per image — not the
    /// resolved/proxied fetch URL passed via `url`, which varies by requested
    /// width and would otherwise fragment the cache per caller.
    func extractColor(from url: URL, cacheKey: String) async -> Color? {
        if let cached = cache[cacheKey] {
            return color(from: cached)
        }
        guard let image = await ImageCache.shared.loadImage(from: url, maxPixelSize: 128) else { return nil }
        guard let rgb = await Self.dominantRGBOffActor(from: image) else { return nil }
        cache(rgb, forKey: cacheKey)
        return Color(red: rgb.r, green: rgb.g, blue: rgb.b)
    }

    /// Synchronous snapshot of the persisted color cache — lets view models
    /// seed era colors at init without a network fetch or actor hop.
    nonisolated static func cachedColors() -> [String: Color] {
        let raw = UserDefaults.standard.dictionary(forKey: cacheKey) as? [String: [Double]] ?? [:]
        return raw.compactMapValues { rgb in
            guard rgb.count == 3 else { return nil }
            return Color(red: rgb[0], green: rgb[1], blue: rgb[2])
        }
    }

    /// Bridges `dominantRGB` onto a detached task so multiple eras can extract
    /// in parallel rather than queueing on this actor's executor.
    nonisolated private static func dominantRGBOffActor(from image: CGImage) async -> RGB? {
        await Task.detached(priority: .userInitiated) {
            Self.dominantRGB(from: image)
        }.value
    }

    // MARK: - Dominant RGB extraction (ColorThief-style median cut approximation)

    struct RGB: Sendable { let r, g, b: Double }

    /// Returns the dominant RGB color from the image using pixel quantization.
    /// Matches what ColorThief's getPalette()[0] returns for the same image.
    nonisolated static func dominantRGB(from cgImage: CGImage) -> RGB? {
        // Downsample to at most 100×100 for speed
        let sampleW = min(cgImage.width, 100)
        let sampleH = min(cgImage.height, 100)

        guard let context = CGContext(
            data: nil,
            width: sampleW,
            height: sampleH,
            bitsPerComponent: 8,
            bytesPerRow: sampleW * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return nil }

        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: sampleW, height: sampleH))
        guard let data = context.data else { return nil }
        let pixels = data.bindMemory(to: UInt8.self, capacity: sampleW * sampleH * 4)

        // Sample filtering — see DECISIONS.md::EraColorExtractor.swift::sample-filtering
        var samples: [Pixel] = []
        samples.reserveCapacity((sampleW / 2 + 1) * (sampleH / 2 + 1))

        let pixelStride = 2
        for y in Swift.stride(from: 0, to: sampleH, by: pixelStride) {
            for x in Swift.stride(from: 0, to: sampleW, by: pixelStride) {
                let o = (y * sampleW + x) * 4
                let r = Int(pixels[o])
                let g = Int(pixels[o + 1])
                let b = Int(pixels[o + 2])
                let a = Int(pixels[o + 3])

                if a < 125 { continue }                       // transparent
                if r > 250 && g > 250 && b > 250 { continue } // pure white
                samples.append(Pixel(r: r, g: g, b: b))
            }
        }

        guard !samples.isEmpty else { return nil }

        // Median cut to 3 levels → up to 8 boxes; the most populated box's
        // average is the dominant color (ColorThief getPalette()[0]).
        var boxes: [ArraySlice<Pixel>] = [samples[...]]
        for _ in 0..<3 {
            var next: [ArraySlice<Pixel>] = []
            for box in boxes {
                if box.count < 2 { next.append(box); continue }
                next.append(contentsOf: Self.medianSplit(box))
            }
            boxes = next
        }

        guard let best = boxes.max(by: { $0.count < $1.count }), !best.isEmpty else { return nil }

        var rSum = 0, gSum = 0, bSum = 0
        for p in best { rSum += p.r; gSum += p.g; bSum += p.b }
        let n = Double(best.count)
        return RGB(r: Double(rSum) / n / 255.0, g: Double(gSum) / n / 255.0, b: Double(bSum) / n / 255.0)
    }

    private struct Pixel: Sendable { let r, g, b: Int }

    /// Splits a box at the median of its widest channel.
    nonisolated private static func medianSplit(_ box: ArraySlice<Pixel>) -> [ArraySlice<Pixel>] {
        var minR = 255, maxR = 0, minG = 255, maxG = 0, minB = 255, maxB = 0
        for p in box {
            minR = min(minR, p.r); maxR = max(maxR, p.r)
            minG = min(minG, p.g); maxG = max(maxG, p.g)
            minB = min(minB, p.b); maxB = max(maxB, p.b)
        }
        let rangeR = maxR - minR, rangeG = maxG - minG, rangeB = maxB - minB

        var sorted = Array(box)
        if rangeR >= rangeG && rangeR >= rangeB {
            sorted.sort { $0.r < $1.r }
        } else if rangeG >= rangeB {
            sorted.sort { $0.g < $1.g }
        } else {
            sorted.sort { $0.b < $1.b }
        }
        let mid = sorted.count / 2
        return [sorted[..<mid], sorted[mid...]]
    }

    // MARK: - Cache helpers

    private func color(from cached: [Double]) -> Color? {
        guard cached.count == 3 else { return nil }
        return Color(red: cached[0], green: cached[1], blue: cached[2])
    }

    private func cache(_ rgb: RGB, forKey key: String) {
        if cache[key] == nil { insertionOrder.append(key) }
        cache[key] = [rgb.r, rgb.g, rgb.b]
        Self.evict(cache: &cache, insertionOrder: &insertionOrder)
        scheduleFlush()
    }

    static let cacheLimit = 200

    /// Trim to `cacheLimit`, dropping oldest-inserted first.
    ///
    /// Oldest-first, not `cache.keys.prefix` — dictionary key order is
    /// arbitrary, so the original eviction threw away whichever entries it
    /// happened to visit, including ones extracted seconds earlier.
    ///
    /// `min()` guards two things: `removeFirst(k)` traps when k exceeds the
    /// count, and `insertionOrder` can legitimately be shorter than `cache`
    /// (it is seeded from the restored keys, but a persisted dictionary larger
    /// than the limit still has to drain over several calls).
    ///
    /// Split out as a pure function purely so the invariant is testable — the
    /// extractor itself is a singleton actor whose init runs once per process.
    nonisolated static func evict(
        cache: inout [String: [Double]], insertionOrder: inout [String]
    ) {
        guard cache.count > cacheLimit else { return }
        let excess = min(cache.count - cacheLimit, insertionOrder.count)
        for k in insertionOrder.prefix(excess) { cache.removeValue(forKey: k) }
        insertionOrder.removeFirst(excess)
    }

    /// Memory is authoritative; UserDefaults is caught up shortly after the
    /// last extraction. Writing on every extraction re-encoded the whole
    /// dictionary (up to 200 entries) per era cover, repeatedly, while the
    /// user was scrolling a cold tracker.
    private func scheduleFlush() {
        flushTask?.cancel()
        flushTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            await self?.flushCache()
        }
    }

    /// Actor-isolated so the debounced task reads `cache` on the actor.
    private func flushCache() {
        UserDefaults.standard.set(cache, forKey: Self.cacheKey)
    }

    /// Write now instead of waiting out the 2s debounce — called when the app
    /// backgrounds, so a session's worth of extracted colours isn't lost to a
    /// force-quit and re-extracted on next launch.
    func flush() {
        guard flushTask != nil else { return }
        flushTask?.cancel()
        flushTask = nil
        flushCache()
    }
}
