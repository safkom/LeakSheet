import SwiftUI
import UIKit

/// Extracts the dominant RGB color from an era image — mirrors ColorThief's approach.
/// Returns actual image RGB values so card gradients, text, and borders match the web app exactly.
actor EraColorExtractor {
    static let shared = EraColorExtractor()

    // Cache: eraName → [r, g, b] in 0-1 range
    private var cache: [String: [Double]]
    private static let cacheKey = "leaksheet_era_rgb_v2"

    private init() {
        cache = UserDefaults.standard.dictionary(forKey: Self.cacheKey) as? [String: [Double]] ?? [:]
    }

    // MARK: - Public API

    /// Extract from an already-loaded UIImage (no download). Used during prefetch.
    func extractColor(fromImage image: UIImage, eraName: String) async -> Color? {
        if let cached = cache[eraName] {
            return color(from: cached)
        }
        // Run pixel sampling off the actor so concurrent extractions don't serialize.
        guard let rgb = await Self.dominantRGBOffActor(from: image) else { return nil }
        cache(rgb, forKey: eraName)
        return Color(red: rgb.r, green: rgb.g, blue: rgb.b)
    }

    /// Extract from a URL — uses ImageCache to avoid re-downloading.
    func extractColor(from url: URL, eraName: String) async -> Color? {
        if let cached = cache[eraName] {
            return color(from: cached)
        }
        guard let image = await ImageCache.shared.loadImage(from: url) else { return nil }
        guard let rgb = await Self.dominantRGBOffActor(from: image) else { return nil }
        cache(rgb, forKey: eraName)
        return Color(red: rgb.r, green: rgb.g, blue: rgb.b)
    }

    /// Bridges `dominantRGB` onto a detached task so multiple eras can extract
    /// in parallel rather than queueing on this actor's executor.
    nonisolated private static func dominantRGBOffActor(from image: UIImage) async -> RGB? {
        await Task.detached(priority: .userInitiated) {
            Self.dominantRGB(from: image)
        }.value
    }

    // MARK: - Dominant RGB extraction (ColorThief-style median cut approximation)

    struct RGB: Sendable { let r, g, b: Double }

    /// Returns the dominant RGB color from the image using pixel quantization.
    /// Matches what ColorThief's getPalette()[0] returns for the same image.
    nonisolated static func dominantRGB(from image: UIImage) -> RGB? {
        guard let cgImage = image.cgImage else { return nil }

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

        // Quantize each pixel to 5-bit buckets (32 levels per channel).
        // Count hits per bucket, accumulate real RGB sums for averaging.
        typealias Bucket = (count: Int, rSum: Int, gSum: Int, bSum: Int)
        var buckets = [Int32: Bucket]()
        buckets.reserveCapacity(512)

        let pixelStride = 2
        for y in Swift.stride(from: 0, to: sampleH, by: pixelStride) {
            for x in Swift.stride(from: 0, to: sampleW, by: pixelStride) {
                let o = (y * sampleW + x) * 4
                let r = Int(pixels[o])
                let g = Int(pixels[o + 1])
                let b = Int(pixels[o + 2])
                let a = Int(pixels[o + 3])

                if a < 128 { continue }              // transparent
                let bright = max(r, g, b)
                if bright < 25 { continue }           // too dark
                let colorfulness = bright - min(r, g, b)
                if bright > 230 && colorfulness < 20 { continue } // near-white

                let key = Int32(r >> 3) * 1024 + Int32(g >> 3) * 32 + Int32(b >> 3)
                var bkt = buckets[key] ?? (0, 0, 0, 0)
                bkt.count += 1; bkt.rSum += r; bkt.gSum += g; bkt.bSum += b
                buckets[key] = bkt
            }
        }

        guard let best = buckets.values.max(by: { $0.count < $1.count }),
              best.count > 0 else { return nil }

        return RGB(
            r: Double(best.rSum) / Double(best.count) / 255.0,
            g: Double(best.gSum) / Double(best.count) / 255.0,
            b: Double(best.bSum) / Double(best.count) / 255.0
        )
    }

    // MARK: - Cache helpers

    private func color(from cached: [Double]) -> Color? {
        guard cached.count == 3 else { return nil }
        return Color(red: cached[0], green: cached[1], blue: cached[2])
    }

    private func cache(_ rgb: RGB, forKey key: String) {
        cache[key] = [rgb.r, rgb.g, rgb.b]
        if cache.count > 200 {
            let excess = cache.count - 200
            for k in cache.keys.prefix(excess) { cache.removeValue(forKey: k) }
        }
        UserDefaults.standard.set(cache, forKey: Self.cacheKey)
    }
}
