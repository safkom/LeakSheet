import SwiftUI

/// Credit tags: featuring, producers, collaboration, refs.
struct CreditTagsView: View {
    let version: SongVersion

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
        }
    }

    private func creditTag(type: CreditType, text: String) -> some View {
        HStack(alignment: .top, spacing: 4) {
            Text(type.label)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(type.color.opacity(0.8))
                .fixedSize()
            Text(text)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(type.color.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}
