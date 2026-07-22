import SwiftUI

/// Quality + availability badges for a song version.
struct BadgeRowView: View {
    let version: SongVersion

    var body: some View {
        // FlowLayout (not HStack) so the quality + availability pills wrap to a
        // second row at accessibility Dynamic Type instead of the trailing pill
        // clipping off the edge.
        FlowLayout(spacing: 5) {
            if let quality = version.quality, !quality.isEmpty {
                let variant = qualityVariant(quality)
                Text(quality)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(variant.foreground)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(variant.background)
                    .clipShape(Capsule())
                    .fixedSize()
                    .accessibilityLabel("Quality: \(quality)")
            }

            if let avail = version.availableLength, !avail.isEmpty {
                let variant = availabilityVariant(avail)
                Text(avail)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(variant.foreground)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(variant.background)
                    .clipShape(Capsule())
                    .fixedSize()
                    .accessibilityLabel("Availability: \(avail)")
            }
        }
    }
}
