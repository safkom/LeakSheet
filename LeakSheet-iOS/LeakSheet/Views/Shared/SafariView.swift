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
}

extension View {
    /// Opens a web link the way the platform expects.
    ///
    /// iOS presents `SFSafariViewController` in a sheet so the user stays in
    /// the app (Reader, share sheet, "Open in Safari" all come free). macOS has
    /// no such controller and the platform convention is the user's own
    /// browser, so it hands off to `NSWorkspace` and clears the binding.
    /// See DECISIONS.md::SafariView.swift::web-sheet.
    func webSheet(item: Binding<SafariItem?>) -> some View {
        modifier(WebSheet(item: item))
    }
}

private struct WebSheet: ViewModifier {
    @Binding var item: SafariItem?

    func body(content: Content) -> some View {
        #if os(iOS)
        content.sheet(item: $item) { SafariView(url: $0.url) }
        #elseif os(macOS)
        content.onChange(of: item?.url) { _, url in
            guard let url else { return }
            NSWorkspace.shared.open(url)
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
