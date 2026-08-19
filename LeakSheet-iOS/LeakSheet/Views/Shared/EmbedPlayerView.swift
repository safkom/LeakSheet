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
                #if os(iOS)
                #if os(iOS)
            .toolbarTitleDisplayMode(.inline)
            #endif
                #endif
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Done") { dismiss() }
                    }
                    ToolbarItem(placement: .primaryAction) {
                        Link(destination: item.originalURL) {
                            Image(systemName: "safari")
                        }
                        .accessibilityLabel("Open in Safari")
                    }
                }
        }
    }
}

private func makeEmbedWebView(url: URL) -> WKWebView {
    let config = WKWebViewConfiguration()
    #if os(iOS)
    // macOS plays inline unconditionally; the property is iOS-only.
    config.allowsInlineMediaPlayback = true
    #endif
    config.mediaTypesRequiringUserActionForPlayback = []
    let webView = WKWebView(frame: .zero, configuration: config)
    #if os(iOS)
    webView.isOpaque = false
    webView.backgroundColor = .black
    #endif
    webView.load(URLRequest(url: url))
    return webView
}

#if os(macOS)
private struct EmbedWebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView { makeEmbedWebView(url: url) }
    func updateNSView(_ webView: WKWebView, context: Context) {}
}
#else
private struct EmbedWebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView { makeEmbedWebView(url: url) }
    func updateUIView(_ webView: WKWebView, context: Context) {}
}
#endif
