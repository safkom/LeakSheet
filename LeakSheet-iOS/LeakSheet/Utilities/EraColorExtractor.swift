import SwiftUI
import UIKit

/// Extracts the dominant RGB color from an era image — mirrors ColorThief's approach.
/// Returns actual image RGB values so card gradients, text, and borders match the web app exactly.
actor EraColorExtractor {
    static let shared = EraColorExtractor()

    // Cache: eraName → [r, g, b] in 0-1 range
    private var cache: [String: [Double]]
    private static let cacheKey = "leaksheet_era_rgb_v3"

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

        // Collect sampled pixels with ColorThief's filter: skip transparent
        // and near-pure-white pixels only. A mostly-white cover keeps its
        // off-white pixels and resolves to a neutral, and a warm multi-tone
        // cover isn't out-voted by one small flat region (median cut groups
        // similar tones into one box instead of splitting them across
        // hundreds of fixed buckets).
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
        cache[key] = [rgb.r, rgb.g, rgb.b]
        if cache.count > 200 {
            let excess = cache.count - 200
            for k in cache.keys.prefix(excess) { cache.removeValue(forKey: k) }
        }
        UserDefaults.standard.set(cache, forKey: Self.cacheKey)
    }
}
