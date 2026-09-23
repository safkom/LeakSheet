import CoreImage.CIFilterBuiltins
import SwiftUI

/// Identifiable wrapper for `.sheet(item:)`, like iOS's SafariItem. Not a blanket
/// `extension URL: Identifiable`, which would leak to every URL in the module.
struct QRItem: Identifiable {
    let url: URL
    var title: String?
    var id: String { url.absoluteString }
}

/// Hand-off for anything tvOS can't open itself: no WebKit and no browser, so a
/// QR code lets the user continue on their phone. See DECISIONS.md::tvOS::qr-handoff.
struct QRCodeSheet: View {
    let url: URL
    var title: String?

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 32) {
            VStack(spacing: 8) {
                Text("Open on your phone")
                    .font(.largeTitle.bold())
                if let title, !title.isEmpty {
                    Text(title)
                        .font(.title3)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                }
            }

            if let code = Self.qrImage(for: url) {
                Image(decorative: code, scale: 1)
                    .interpolation(.none)  // keep the modules crisp when scaled up
                    .resizable()
                    .frame(width: 460, height: 460)
                    .padding(24)
                    .background(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 24))
            } else {
                ContentUnavailableView("Couldn't build a QR code", systemImage: "qrcode")
            }

            Text(url.absoluteString)
                .font(.callout.monospaced())
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 1000)

            Button("Done") { dismiss() }
        }
        .padding(60)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.lsBackground)
        // The Menu button already dismisses; this keeps the binding in sync.
        .onExitCommand { dismiss() }
    }

    init(item: QRItem) {
        self.url = item.url
        self.title = item.title
    }

    init(url: URL, title: String? = nil) {
        self.url = url
        self.title = title
    }

    private static func qrImage(for url: URL) -> CGImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(url.absoluteString.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        // CIQRCodeGenerator emits one pixel per module; scale up before
        // rasterizing so the bitmap has real resolution to display.
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 12, y: 12))
        return CIContext().createCGImage(scaled, from: scaled.extent)
    }
}
