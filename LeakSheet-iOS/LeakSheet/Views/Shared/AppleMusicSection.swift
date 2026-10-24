import SwiftUI

/// "Open in Apple Music" for a version the tracker lists as on streaming; empty when no exact match.
struct AppleMusicSection: View {
    let artist: String
    let title: String

    @State private var url: URL?

    var body: some View {
        Group {
            if let url {
                Link(destination: url) {
                    Label("Open in Apple Music", systemImage: "music.note")
                        .frame(maxWidth: .infinity, minHeight: Metrics.hitTarget)
                }
                .buttonStyle(.bordered)
            }
        }
        .task(id: "\(artist)|\(title)") {
            url = await AppleMusicCatalog.shared.songURL(artist: artist, title: title)
        }
    }
}
