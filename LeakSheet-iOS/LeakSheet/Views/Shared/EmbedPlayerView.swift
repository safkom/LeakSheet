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
                // Two players at once: the Mac has no audio session to arbitrate.
                .onAppear { AudioEngine.shared.pause() }
                .navigationTitle(item.title)
                #if os(iOS)
                .toolbarTitleDisplayMode(.inline)
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

/// Keeps the sheet on the provider's player: it has no address bar, so a page the
/// player links to opens in the browser instead of inside it.
final class EmbedNavigationPolicy: NSObject, WKNavigationDelegate {
    /// The providers' own sites, subdomains included (a consent page is one of them).
    nonisolated static let playerSites = ["youtube.com", "youtube-nocookie.com", "vimeo.com", "soundcloud.com"]

    nonisolated static func staysInPlayer(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased() else { return url.scheme == "about" }
        return playerSites.contains { host == $0 || host.hasSuffix("." + $0) }
    }

    func webView(
        _ webView: WKWebView, decidePolicyFor action: WKNavigationAction
    ) async -> WKNavigationActionPolicy {
        guard action.targetFrame?.isMainFrame != false, let url = action.request.url else { return .allow }
        if Self.staysInPlayer(url) { return .allow }
        if action.navigationType == .linkActivated, SafariItem.isWebURL(url) {
            #if os(macOS)
            NSWorkspace.shared.open(url)
            #else
            await UIApplication.shared.open(url)
            #endif
        }
        return .cancel
    }
}

#if os(macOS)
private struct EmbedWebView: NSViewRepresentable {
    let url: URL

    func makeCoordinator() -> EmbedNavigationPolicy { EmbedNavigationPolicy() }
    func makeNSView(context: Context) -> WKWebView {
        let webView = makeEmbedWebView(url: url)
        webView.navigationDelegate = context.coordinator
        return webView
    }
    func updateNSView(_ webView: WKWebView, context: Context) {}
}
#else
private struct EmbedWebView: UIViewRepresentable {
    let url: URL

    func makeCoordinator() -> EmbedNavigationPolicy { EmbedNavigationPolicy() }
    func makeUIView(context: Context) -> WKWebView {
        let webView = makeEmbedWebView(url: url)
        webView.navigationDelegate = context.coordinator
        return webView
    }
    func updateUIView(_ webView: WKWebView, context: Context) {}
}
#endif
