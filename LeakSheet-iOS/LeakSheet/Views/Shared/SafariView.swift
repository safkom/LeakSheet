import SwiftUI

#if os(iOS)
import SafariServices
#elseif os(macOS)
import AppKit
#endif

/// Identifiable wrapper for `.sheet(item:)` presentation.
struct SafariItem: Identifiable {
    let url: URL
    var id: String { url.absoluteString }

    /// Tracker cells are untrusted: only http(s) may reach SFSafariViewController
    /// (it throws on anything else) or NSWorkspace (it runs any URL handler).
    nonisolated static func isWebURL(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased() else { return false }
        return (scheme == "http" || scheme == "https") && url.host?.isEmpty == false
    }
}

extension View {
    /// Opens a web link the way the platform expects: iOS presents
    /// `SFSafariViewController` in a sheet; macOS hands off to the user's browser
    /// via `NSWorkspace` and clears the binding.
    func webSheet(item: Binding<SafariItem?>) -> some View {
        modifier(WebSheet(item: item))
    }
}

private struct WebSheet: ViewModifier {
    @Binding var item: SafariItem?

    private var webItem: Binding<SafariItem?> {
        Binding(
            get: { item.flatMap { SafariItem.isWebURL($0.url) ? $0 : nil } },
            set: { item = $0 }
        )
    }

    func body(content: Content) -> some View {
        #if os(iOS)
        content
            .sheet(item: webItem) { SafariView(url: $0.url) }
            .onChange(of: item?.url) { _, url in
                if let url, !SafariItem.isWebURL(url) { item = nil }
            }
        #elseif os(macOS)
        content.onChange(of: item?.url) { _, url in
            guard let url else { return }
            if SafariItem.isWebURL(url) { NSWorkspace.shared.open(url) }
            item = nil
        }
        #else
        content
        #endif
    }
}

#if os(iOS)
/// In-app Safari sheet — replaces `UIApplication.shared.open` for web links
/// so the user stays in the app.
private struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        SFSafariViewController(url: url)
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
#endif
