import SwiftUI

/// Card displaying a recently viewed tracker.
struct RecentTrackerCardView: View {
    let entry: RecentTrackersManager.RecentTracker
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 12) {
                // Thumbnail
                Group {
                    if let artUrl = entry.artUrl {
                        CachedImage(url: APIClient.shared.imageProxyURL(for: artUrl)) {
                            initialsPlaceholder
                        }
                    } else {
                        initialsPlaceholder
                    }
                }
                .frame(width: 48, height: 48)
                .clipShape(RoundedRectangle(cornerRadius: 8))

                // Info
                VStack(alignment: .leading, spacing: 3) {
                    Text(entry.name)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(1)

                    Text(statLine)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(Color.lsBorder, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    private var statLine: String {
        var parts = ["\(entry.totalSongs) songs"]
        if entry.availableCount > 0 { parts.append("\(entry.availableCount) available") }
        if entry.snippetCount > 0 { parts.append("\(entry.snippetCount) snippets") }
        return parts.joined(separator: " · ")
    }

    private var initialsPlaceholder: some View {
        let initials = entry.name
            .split(separator: " ")
            .prefix(2)
            .compactMap { $0.first.map { String($0).uppercased() } }
            .joined()
        return Text(initials)
            .font(.subheadline.bold())
            .foregroundStyle(.secondary)
            .frame(width: 48, height: 48)
            .background(Color.lsCard)
    }
}
