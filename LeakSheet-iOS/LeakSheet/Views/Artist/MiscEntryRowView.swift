import SwiftUI

/// Row for one Misc / Music Videos entry — name, type capsule, and metadata.
/// Misc entries are separate from the era/song tree, so this row doesn't
/// reuse SongRowView (which requires a Song).
struct MiscEntryRowView: View {
    let entry: MiscEntry
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                Text(entry.name)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.primary)
                    .lineLimit(2)

                HStack(spacing: 5) {
                    if let type = entry.entryType, !type.isEmpty {
                        typePill(type)
                    }
                    if let quality = entry.quality, !quality.isEmpty {
                        badgePill(quality, variant: qualityVariant(quality))
                            .accessibilityLabel("Quality: \(quality)")
                    }
                    if let avail = entry.available, !avail.isEmpty {
                        badgePill(avail, variant: availabilityVariant(avail))
                            .accessibilityLabel("Availability: \(avail)")
                    }
                }

                HStack(spacing: 6) {
                    if let date = entry.date, !date.isEmpty, date.lowercased() != "n/a" {
                        metaText(date, icon: "calendar")
                    }
                    if let length = entry.length, !length.isEmpty, length.lowercased() != "n/a" {
                        metaText(length, icon: "clock")
                    }
                    if entry.streaming == true {
                        metaText("Streaming", icon: "antenna.radiowaves.left.and.right")
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if entry.isStreamable {
                Image(systemName: "play.circle")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
            } else if !entry.links.isEmpty {
                Image(systemName: "arrow.up.right.square")
                    .font(.body)
                    .foregroundStyle(.tertiary)
                    .accessibilityHidden(true)
            }
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
    }

    // MARK: - Pieces

    private func typePill(_ type: String) -> some View {
        Text(type.uppercased())
            .font(.caption2.weight(.bold))
            .tracking(0.5)
            .foregroundStyle(Color.lsAccent)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.lsAccent.opacity(0.12))
            .clipShape(Capsule())
            .fixedSize()
            .accessibilityLabel("Type: \(type)")
    }

    private func badgePill(_ text: String, variant: BadgeVariant) -> some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(variant.foreground)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(variant.background)
            .clipShape(Capsule())
            .fixedSize()
    }

    private func metaText(_ text: String, icon: String) -> some View {
        HStack(spacing: 3) {
            Image(systemName: icon)
                .font(.caption2)
            Text(text)
                .font(.caption2)
        }
        .foregroundStyle(.secondary)
    }
}
