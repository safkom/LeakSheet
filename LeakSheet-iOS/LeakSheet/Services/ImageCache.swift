import ImageIO
import UIKit

/// In-memory image cache backed by NSCache, with URLSession disk cache underneath.
/// Actor-isolated for thread safety from any async context.
///
/// Images are decoded through ImageIO's thumbnail path at a bounded pixel
/// size — a full-resolution `UIImage(data:)` of a 2000×2000 cover costs
/// ~16 MB of bitmap and decodes on first draw (main thread); a 320px bucket
/// costs ~0.4 MB and decodes here, off-main.
actor ImageCache {
    static let shared = ImageCache()

    /// Decode-size buckets. Keeping the set small means a URL is decoded at
    /// most a few times; callers snap their point size to a bucket.
    // 1600 added 2026-07-17 — matches the backend buckets; full-screen
    // Now Playing art was upscaled from 1280 on ~1290px displays.
    static let sizeBuckets = [128, 320, 640, 1280, 1600]

    private let memCache = NSCache<NSString, UIImage>()
    private let session: URLSession

    private init() {
        memCache.countLimit = 300
        memCache.totalCostLimit = 128 * 1024 * 1024 // 128 MB

        let config = URLSessionConfiguration.default
        config.urlCache = URLCache(
            memoryCapacity: 20 * 1024 * 1024,  // 20 MB
            diskCapacity: 150 * 1024 * 1024     // 150 MB
        )
        config.timeoutIntervalForRequest = 15
        session = URLSession(configuration: config)

        // Purge in-memory images on memory pressure.
        // Observer intentionally not stored: ImageCache is a process-lifetime singleton.
        NotificationCenter.default.addObserver(
            forName: UIApplication.didReceiveMemoryWarningNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { [weak self] in await self?.evictAll() }
        }
    }

    private func evictAll() {
        memCache.removeAllObjects()
    }

    /// Full purge (Settings → Clear cache): in-memory images plus the
    /// URLCache's disk store.
    func clearAll() {
        memCache.removeAllObjects()
        session.configuration.urlCache?.removeAllCachedResponses()
    }

    /// Smallest bucket that covers `points` at the given display scale.
    nonisolated static func bucket(forPointSize points: CGFloat, scale: CGFloat) -> Int {
        let pixels = Int((points * scale).rounded(.up))
        for bucket in sizeBuckets where pixels <= bucket {
            return bucket
        }
        return sizeBuckets[sizeBuckets.count - 1]
    }

    private nonisolated static func cacheKey(_ url: URL, _ maxPixelSize: Int) -> NSString {
        "\(url.absoluteString)#\(maxPixelSize)" as NSString
    }

    /// Returns a cached image synchronously (nil if not in memory cache).
    func cachedImage(for url: URL, maxPixelSize: Int = 1600) -> UIImage? {
        memCache.object(forKey: Self.cacheKey(url, maxPixelSize))
    }

    /// Loads an image, using memory cache → disk/network, decoded at most
    /// `maxPixelSize` on its longest side.
    func loadImage(from url: URL, maxPixelSize: Int = 1280) async -> UIImage? {
        let key = Self.cacheKey(url, maxPixelSize)
        if let hit = memCache.object(forKey: key) { return hit }
        guard let (data, _) = try? await session.data(from: url),
              let image = Self.downsampled(data: data, maxPixelSize: maxPixelSize) else { return nil }
        let cost = Int(image.size.width * image.size.height * 4 * image.scale * image.scale)
        memCache.setObject(image, forKey: key, cost: cost)
        return image
    }

    /// Decode via ImageIO's thumbnail API — bounded memory, and the bitmap is
    /// materialized here (ShouldCacheImmediately) instead of lazily on the
    /// main thread at first draw.
    private nonisolated static func downsampled(data: Data, maxPixelSize: Int) -> UIImage? {
        let sourceOptions = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, sourceOptions) else {
            return nil
        }
        let thumbnailOptions = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixelSize,
        ] as CFDictionary
        guard let cgImage = CGImageSourceCreateThumbnailAtIndex(source, 0, thumbnailOptions) else {
            return nil
        }
        return UIImage(cgImage: cgImage)
    }
}
