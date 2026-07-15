import SwiftUI

/// General-purpose cached image view using ImageCache.
/// Loads from memory cache instantly, falls back to network.
/// `maxPixelSize` bounds the decode (see ImageCache.sizeBuckets) — pass the
/// bucket matching the display size so full-res bitmaps never materialize.
struct CachedImage<Placeholder: View>: View {
    let url: URL?
    var maxPixelSize: Int = 1280
    @ViewBuilder var placeholder: () -> Placeholder

    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
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
