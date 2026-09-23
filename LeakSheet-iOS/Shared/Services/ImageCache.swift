import CoreGraphics
import Foundation
import ImageIO

/// In-memory image cache backed by NSCache, with URLSession disk cache underneath.
///
/// Decodes through ImageIO's thumbnail path at a bounded pixel size, off-main (a
/// full-resolution cover is ~16 MB of bitmap decoded on first draw). The currency
/// type is `CGImage`: see DECISIONS.md::ImageCache.swift::cgimage-currency.
actor ImageCache {
    static let shared = ImageCache()

    private let memCache = NSCache<NSString, CGImage>()
    private let session: URLSession
    /// Must be retained: a DispatchSource is cancelled when its last reference drops.
    private let memoryPressure: DispatchSourceMemoryPressure

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

        // Purge in-memory images on memory pressure. The dispatch source works on every
        // platform; didReceiveMemoryWarningNotification has no macOS equivalent.
        let source = DispatchSource.makeMemoryPressureSource(
            eventMask: [.warning, .critical],
            queue: .main
        )
        memoryPressure = source
        source.setEventHandler { [weak self] in
            Task { [weak self] in await self?.evictAll() }
        }
        source.resume()
    }

    private func evictAll() {
        memCache.removeAllObjects()
    }

    /// On-disk bytes held by the image URLCache (Clear cache empties it too).
    func diskUsageBytes() -> Int64 {
        Int64(session.configuration.urlCache?.currentDiskUsage ?? 0)
    }

    /// Full purge (Settings → Clear cache): in-memory images plus the
    /// URLCache's disk store.
    func clearAll() {
        memCache.removeAllObjects()
        session.configuration.urlCache?.removeAllCachedResponses()
    }

    private nonisolated static func cacheKey(_ url: URL, _ maxPixelSize: Int) -> NSString {
        "\(url.absoluteString)#\(maxPixelSize)" as NSString
    }

    /// Returns a cached image synchronously (nil if not in memory cache).
    func cachedImage(for url: URL, maxPixelSize: Int = 1600) -> CGImage? {
        memCache.object(forKey: Self.cacheKey(url, maxPixelSize))
    }

    /// Loads an image, using memory cache → disk/network, decoded at most
    /// `maxPixelSize` on its longest side.
    ///
    /// Retries once on a throttle or server error: a nil result reads as "no such
    /// image", and callers never ask again.
    func loadImage(from url: URL, maxPixelSize: Int = 1280) async -> CGImage? {
        let key = Self.cacheKey(url, maxPixelSize)
        if let hit = memCache.object(forKey: key) { return hit }

        for attempt in 0...1 {
            guard let (data, response) = try? await session.data(from: url) else { return nil }
            if let http = response as? HTTPURLResponse, Self.isTransient(http.statusCode) {
                guard attempt == 0, !Task.isCancelled else { return nil }
                try? await Task.sleep(for: .seconds(Self.retryDelay(after: http)))
                continue
            }
            guard let image = await Self.downsampledOffActor(data: data, maxPixelSize: maxPixelSize)
            else { return nil }
            memCache.setObject(image, forKey: key, cost: image.width * image.height * 4)
            return image
        }
        return nil
    }

    /// 429 and 5xx are "ask again"; a 404 or a corrupt body is not.
    nonisolated static func isTransient(_ status: Int) -> Bool {
        status == 429 || (500...599).contains(status)
    }

    /// Honour `Retry-After` when the server sends one, clamped so a hostile or
    /// mistaken value can't park an era card for a minute.
    nonisolated static func retryDelay(after response: HTTPURLResponse) -> Double {
        let header = response.value(forHTTPHeaderField: "Retry-After").flatMap(Double.init) ?? 1
        return min(max(header, 0.5), 3)
    }

    /// Bridges `downsampled` onto a detached task, like
    /// `EraColorExtractor.dominantRGBOffActor`: `nonisolated` alone still runs on this
    /// actor's executor when called from it, serializing every decode behind the cache.
    private nonisolated static func downsampledOffActor(
        data: Data, maxPixelSize: Int
    ) async -> CGImage? {
        await Task.detached(priority: .userInitiated) {
            Self.downsampled(data: data, maxPixelSize: maxPixelSize)
        }.value
    }

    /// Decode via ImageIO's thumbnail API — bounded memory, and the bitmap is
    /// materialized here (ShouldCacheImmediately) instead of lazily on the
    /// main thread at first draw.
    private nonisolated static func downsampled(data: Data, maxPixelSize: Int) -> CGImage? {
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
        return CGImageSourceCreateThumbnailAtIndex(source, 0, thumbnailOptions)
    }
}
