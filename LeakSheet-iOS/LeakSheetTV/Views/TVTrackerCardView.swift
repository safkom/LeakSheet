import SwiftUI

/// A focusable tracker tile, used by both Browse and Recents.
/// `.buttonStyle(.card)` gives the standard tvOS focus lift and parallax for
/// free — there is no hover or pointer here, focus IS the selection model.
struct TVTrackerCardView: View {
    let title: String
    var subtitle: String?
    var detail: String?
    var artURL: URL?
    var isBest = false
    var isOutdated = false
    var loading = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 0) {
                ZStack {
                    if let artURL {
                        CachedImage(url: artURL, maxPixelSize: 640) {
                            initialsArt
                        }
                        .aspectRatio(contentMode: .fill)
                    } else {
                        initialsArt
                    }
                    if loading {
                        Color.black.opacity(0.55)
                        ProgressView()
                    }
                }
                .frame(height: 200)
                .clipped()

                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Text(title)
                            .font(.headline)
                            .lineLimit(1)
                        if isBest {
                            Image(systemName: "star.fill")
                                .font(.caption)
                                .foregroundStyle(.yellow)
                                .accessibilityLabel("Best of")
                        }
                    }
                    if let subtitle, !subtitle.isEmpty {
                        Text(subtitle)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    HStack(spacing: 8) {
                        if let detail, !detail.isEmpty {
                            Text(detail)
                                .font(.caption2.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        if isOutdated {
                            Text("outdated")
                                .font(.caption2)
                                .foregroundStyle(.orange)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
            }
            .frame(width: 340)
            .background(Color.lsCard)
        }
        .buttonStyle(.card)
    }

    private var initialsArt: some View {
        ZStack {
            Color.lsCard
            Text(Format.initials(title))
                .font(.largeTitle.bold())
                .foregroundStyle(.secondary)
        }
    }
}
