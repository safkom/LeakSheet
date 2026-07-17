import SwiftUI
import WebKit

/// The item behind an embed sheet: the provider's official player URL plus
/// the original link for the "Open in Safari" escape hatch.
struct EmbedItem: Identifiable {
    let originalURL: URL
    let embedURL: URL
    let title: String

    var id: String { originalURL.absoluteString }
}

/// Official-embed playback sheet for YouTube / Vimeo / SoundCloud — the
/// ToS-safe in-app path (their iframe players, not stream extraction).
struct EmbedPlayerView: View {
    let item: EmbedItem
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            EmbedWebView(url: item.embedURL)
                .ignoresSafeArea(edges: .bottom)
                .navigationTitle(item.title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button("Done") { dismiss() }
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Link(destination: item.originalURL) {
                            Image(systemName: "safari")
                        }
                        .accessibilityLabel("Open in Safari")
                    }
                }
        }
    }
}

private struct EmbedWebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}
}
