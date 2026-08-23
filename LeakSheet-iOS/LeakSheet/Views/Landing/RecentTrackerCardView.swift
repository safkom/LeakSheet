import SwiftUI

/// Card displaying a recently viewed tracker.
struct RecentTrackerCardView: View {
    let entry: RecentTrackersManager.RecentTracker
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 12) {
                // Explicit 1:1 crop — see DECISIONS.md::RecentTrackerCardView.swift::thumbnail-aspect-ratio
                Group {
                    if let artUrl = entry.artUrl {
                        CachedImage(url: APIClient.shared.imageProxyURL(for: artUrl, width: 320), maxPixelSize: 320) {
                            initialsPlaceholder
                        }
                    } else {
                        initialsPlaceholder
                    }
                }
                .aspectRatio(1, contentMode: .fill)
                .frame(width: 48, height: 48)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .clipped()

                // Info
                VStack(alignment: .leading, spacing: 3) {
                    Text(entry.name)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(1)

                    Text(statLine)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .accessibilityHidden(true)
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

    // Matches header's navigationSubtitle count — see DECISIONS.md::RecentTrackerCardView.swift::stat-line-count
    private var statLine: String {
        var parts = ["\(entry.totalVersions) tracks"]
        if entry.availableCount > 0 { parts.append("\(entry.availableCount) available") }
        if entry.snippetCount > 0 { parts.append("\(entry.snippetCount) snippets") }
        return parts.joined(separator: " · ")
    }

    private var initialsPlaceholder: some View {
        Text(Format.initials(entry.name))
            .font(.subheadline.bold())
            .foregroundStyle(.secondary)
            .frame(width: 48, height: 48)
            .background(Color.lsCard)
    }
}
