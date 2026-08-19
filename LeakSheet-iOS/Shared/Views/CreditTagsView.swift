import SwiftUI

/// Credit tags: featuring, producers, collaboration, refs.
struct CreditTagsView: View {
    let version: SongVersion

    /// See `BadgePill` — the per-credit tints are picked for the app background
    /// and vanish on a selected row's accent fill.
    @Environment(\.backgroundProminence) private var prominence

    private var onProminentBackground: Bool { prominence == .increased }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let feat = version.featuring, !feat.isEmpty {
                creditTag(type: .featuring, text: feat)
            }
            if let prod = version.producers, !prod.isEmpty {
                creditTag(type: .producers, text: prod)
            }
            if let collab = version.collaboration, !collab.isEmpty {
                creditTag(type: .collaboration, text: collab)
            }
            if let refs = version.refs, !refs.isEmpty {
                creditTag(type: .refs, text: refs)
            }
            if let director = version.director, !director.isEmpty {
                creditTag(type: .director, text: director)
            }
            if let credited = version.creditedArtists, !credited.isEmpty {
                creditTag(type: .creditedArtists, text: credited)
            }
        }
    }

    private func creditTag(type: CreditType, text: String) -> some View {
        HStack(alignment: .top, spacing: 4) {
            Text(type.label)
                .font(.caption2.weight(.semibold))
                // Full opacity, and the wash below is 15%: the same composite
                // BadgePill uses. At 0.8 over a 10% wash `director` could not
                // clear AA at any brightness — the composite was the defect,
                // not the hue.
                .foregroundStyle(onProminentBackground
                    ? AnyShapeStyle(.background.opacity(0.85))
                    : AnyShapeStyle(type.color))
                .fixedSize()
            Text(text)
                .font(.caption2)
                .foregroundStyle(onProminentBackground ? AnyShapeStyle(.background) : AnyShapeStyle(.secondary))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(onProminentBackground ? Color.white.opacity(0.18) : type.color.opacity(0.15))
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(type.accessibilityLabel) \(text)")
    }
}
