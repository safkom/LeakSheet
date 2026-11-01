import SwiftUI

/// The era's name, or its title logo drawn whole in its place (docs/decisions.md::
/// fetcher.py::_is_title_art). The name shows until the logo loads; VoiceOver reads it.
struct EraTitle<Label: View>: View {
    let era: Era
    let maxHeight: CGFloat
    var alignment: Alignment = .leading
    @ViewBuilder var label: () -> Label

    @State private var logo: CGImage?

    var body: some View {
        Group {
            if let logo {
                Image(decorative: logo, scale: 1)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: .infinity, maxHeight: maxHeight, alignment: alignment)
                    // Logos are often white on clear: the shadow keeps them legible on light backgrounds.
                    .shadow(color: .black.opacity(0.45), radius: 1.5)
                    .accessibilityRepresentation { label() }
            } else {
                label()
            }
        }
        .task(id: era.titleArtUrl) {
            guard let title = era.titleArtUrl,
                  let url = APIClient.shared.imageProxyURL(for: title, width: 640) else {
                logo = nil
                return
            }
            if let cached = await ImageCache.shared.cachedImage(for: url, maxPixelSize: 640) {
                logo = cached
                return
            }
            // Wrong logo is worse than the name text while the new one loads.
            logo = nil
            logo = await ImageCache.shared.loadImage(from: url, maxPixelSize: 640)
        }
    }
}
