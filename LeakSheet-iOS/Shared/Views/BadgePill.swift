import SwiftUI

/// The single capsule pill for quality / availability text — previously five
/// near-identical implementations across song rows, misc rows, favourites,
/// and the description sheet.
struct BadgePill: View {
    let text: String
    let variant: BadgeVariant

    /// VoiceOver prefix, e.g. "Quality" → "Quality: CD Quality".
    var accessibilityPrefix: String? = nil
    /// Larger type and padding for the description sheet, which reads at
    /// arm's length rather than inside a dense list. This was the fifth
    /// near-identical copy the comment above claims to have folded in.
    var prominent: Bool = false

    var body: some View {
        Text(text)
            .font(prominent ? .footnote.weight(.semibold) : .caption2.weight(.semibold))
            .foregroundStyle(variant.color)
            .padding(.horizontal, prominent ? 10 : 7)
            .padding(.vertical, prominent ? 5 : 3)
            // Opaque base under the tint, so the pill composites against the
            // app background rather than whatever row is behind it. The tint is
            // only 15%; over a selected row's fill it drifted off the contrast
            // the palette is tested at, which is why the pill used to invert
            // itself on selection and look washed out.
            .background {
                Capsule()
                    .fill(Color.lsBackground)
                    .overlay { Capsule().fill(variant.background) }
            }
            .clipShape(Capsule())
            .fixedSize()
            .accessibilityLabel(accessibilityPrefix.map { "\($0): \(text)" } ?? text)
    }
}

/// The two pills for a version per SPEC §12 display logic, wrapped in a
/// FlowLayout so they break to a second row at accessibility Dynamic Type.
struct DedupedBadgePills: View {
    let quality: String?
    let availability: String?

    var body: some View {
        FlowLayout(spacing: 5) {
            if let primary = BadgeLogic.primaryPill(quality: quality, availability: availability) {
                BadgePill(
                    text: primary.text,
                    variant: primary.isQuality
                        ? qualityVariant(primary.text)
                        : availabilityVariant(primary.text),
                    accessibilityPrefix: primary.isQuality ? "Quality" : "Availability"
                )
            }
            if let avail = BadgeLogic.availabilityPill(quality: quality, availability: availability) {
                BadgePill(
                    text: avail.text,
                    variant: availabilityVariant(avail.text),
                    accessibilityPrefix: "Availability"
                )
            }
        }
    }
}

/// Shared music-note artwork placeholder — previously eight near-identical
/// inline implementations. Size it with .frame at the call site.
struct ArtworkPlaceholder: View {
    var cornerRadius: CGFloat = 6

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius)
            .fill(Color.lsCard)
            .overlay {
                Image(systemName: "music.note")
                    .foregroundStyle(.secondary)
            }
    }
}
