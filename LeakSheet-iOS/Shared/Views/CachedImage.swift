import SwiftUI

/// General-purpose cached image view using ImageCache.
/// Loads from memory cache instantly, falls back to network.
/// `maxPixelSize` bounds the decode (see ImageCache.sizeBuckets) — pass the
/// bucket matching the display size so full-res bitmaps never materialize.
struct CachedImage<Placeholder: View>: View {
    let url: URL?
    var maxPixelSize: Int = 1280
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
                return
            }
            // Clear so the PREVIOUS url's bitmap isn't left on screen under
            // the new one's label while this resolves. Deliberate trade: the
            // miss above is a MEMORY miss, and `loadImage` can still be served
            // from URLCache on disk, so this does flash the placeholder on a
            // warm-disk hit. Showing the wrong art is worse than showing none,
            // and the in-memory fast path above already covers the common case.
            image = nil
            if let loaded = await ImageCache.shared.loadImage(from: url, maxPixelSize: maxPixelSize) {
                image = loaded
            } else {
                // Network/load failed — surface the placeholder instead of
                // leaving the previously-loaded image visible.
                image = nil
            }
        }
    }
}

extension CachedImage where Placeholder == DefaultCachedImagePlaceholder {
    init(url: URL?, maxPixelSize: Int = 1280) {
        self.url = url
        self.maxPixelSize = maxPixelSize
        self.placeholder = { DefaultCachedImagePlaceholder() }
    }
}

struct DefaultCachedImagePlaceholder: View {
    var body: some View {
        Image(systemName: "music.note")
            .foregroundStyle(.secondary)
    }
}
