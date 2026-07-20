import SafariServices
import SwiftUI

/// In-app Safari sheet — replaces `UIApplication.shared.open` for web links
/// so the user stays in the app (Reader, share sheet, and "Open in Safari"
/// all come free with SFSafariViewController).
struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        SFSafariViewController(url: url)
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}

/// Identifiable wrapper for `.sheet(item:)` presentation.
struct SafariItem: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}
