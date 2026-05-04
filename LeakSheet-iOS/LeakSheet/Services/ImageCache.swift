import UIKit

/// In-memory image cache backed by NSCache, with URLSession disk cache underneath.
/// Actor-isolated for thread safety from any async context.
actor ImageCache {
    static let shared = ImageCache()

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

    /// Returns a cached image synchronously (nil if not in memory cache).
    func cachedImage(for url: URL) -> UIImage? {
        memCache.object(forKey: url.absoluteString as NSString)
    }

    /// Loads an image, using memory cache → disk/network.
    func loadImage(from url: URL) async -> UIImage? {
        let key = url.absoluteString as NSString
        if let hit = memCache.object(forKey: key) { return hit }
        guard let (data, _) = try? await session.data(from: url),
              let image = UIImage(data: data) else { return nil }
        let cost = Int(image.size.width * image.size.height * 4)
        memCache.setObject(image, forKey: key, cost: cost)
        return image
    }

    /// Prefetches a batch of URLs in parallel, returns when all complete (or fail).
    func prefetchAll(_ urls: [URL]) async {
        await withTaskGroup(of: Void.self) { group in
            for url in urls {
                group.addTask { _ = await self.loadImage(from: url) }
            }
        }
    }
}
