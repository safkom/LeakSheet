import SwiftUI

/// General-purpose cached image view using ImageCache: memory cache first, then
/// network. Pass the `maxPixelSize` bucket matching the display size (128, 320,
/// 640, 1280 or 1600, the backend's resize widths) so full-res bitmaps never exist.
struct CachedImage<Placeholder: View>: View {
    let url: URL?
    var maxPixelSize: Int = 1280
    /// Runs each time a bitmap is shown, cached or loaded — era cards extract
    /// their colour here (the extractor caches, so repeats are cheap).
    var onLoad: ((CGImage) async -> Void)? = nil
    @ViewBuilder var placeholder: () -> Placeholder

    @State private var image: CGImage?

    var body: some View {
        Group {
            if let image {
                Image(decorative: image, scale: 1)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
            } else {
                placeholder()
            }
        }
        .task(id: url) {
            guard let url else {
                image = nil
                return
            }
            if let cached = await ImageCache.shared.cachedImage(for: url, maxPixelSize: maxPixelSize) {
                image = cached
                await onLoad?(cached)
                return
            }
            // Clear so the PREVIOUS url's bitmap isn't shown under the new label. This can
            // flash the placeholder on a warm-disk hit; wrong art is worse than none.
            image = nil
            if let loaded = await ImageCache.shared.loadImage(from: url, maxPixelSize: maxPixelSize) {
                image = loaded
                await onLoad?(loaded)
            } else {
                // Network/load failed — surface the placeholder instead of
                // leaving the previously-loaded image visible.
                image = nil
            }
        }
    }
}
