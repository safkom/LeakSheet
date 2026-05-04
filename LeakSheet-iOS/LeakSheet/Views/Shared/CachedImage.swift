import SwiftUI

/// General-purpose cached image view using ImageCache.
/// Loads from memory cache instantly, falls back to network.
struct CachedImage<Placeholder: View>: View {
    let url: URL?
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
            if let cached = await ImageCache.shared.cachedImage(for: url) {
                image = cached
                return
            }
            if let loaded = await ImageCache.shared.loadImage(from: url) {
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
    init(url: URL?) {
        self.url = url
        self.placeholder = { DefaultCachedImagePlaceholder() }
    }
}

struct DefaultCachedImagePlaceholder: View {
    var body: some View {
        Image(systemName: "music.note")
            .foregroundStyle(.secondary)
    }
}
