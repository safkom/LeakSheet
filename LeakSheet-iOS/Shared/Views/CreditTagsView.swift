import SwiftUI

/// Credit tags: featuring, producers, collaboration, refs.
struct CreditTagsView: View {
    let version: SongVersion

    /// Lay the tags out in one flowing line instead of stacking them (desktop rows,
    /// where width isn't the scarce axis).
    var inline = false

    var body: some View {
        layout {
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

    @ViewBuilder
    private func layout<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        if inline {
            FlowLayout(spacing: 5) { content() }
        } else {
            VStack(alignment: .leading, spacing: 4) { content() }
        }
    }

    private func creditTag(type: CreditType, text: String) -> some View {
        HStack(alignment: .top, spacing: 4) {
            Text(type.label)
                .font(.caption2.weight(.semibold))
                // Full opacity over a 15% wash, the same composite as BadgePill, so every
                // credit colour clears AA.
                .foregroundStyle(type.color)
                .fixedSize()
            Text(text)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        // Opaque base — see BadgePill.
        .background {
            RoundedRectangle(cornerRadius: 4)
                .fill(Color.lsBackground)
                .overlay { RoundedRectangle(cornerRadius: 4).fill(type.color.opacity(0.15)) }
        }
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(type.accessibilityLabel) \(text)")
    }
}

/// A version's credits as one line of text — "feat. X · prod. Y" — for list rows;
/// it wraps like prose at large text sizes instead of taking a line per pill.
struct CreditLineView: View {
    let version: SongVersion

    private var parts: [(CreditType, String)] {
        [
            (.featuring, version.featuring), (.producers, version.producers),
            (.collaboration, version.collaboration), (.refs, version.refs),
            (.director, version.director), (.creditedArtists, version.creditedArtists),
        ].compactMap { type, text in
            guard let text, !text.isEmpty else { return nil }
            return (type, text)
        }
    }

    var body: some View {
        let parts = parts
        if !parts.isEmpty {
            parts.enumerated().reduce(Text(verbatim: "")) { line, item in
                let (type, text) = item.element
                let label = Text(type.label).foregroundStyle(type.color).fontWeight(.semibold)
                let separator = item.offset == 0 ? "" : "  ·  "
                return Text("\(line)\(separator)\(label) \(text)")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(3)
            .accessibilityLabel(parts.map { "\($0.0.accessibilityLabel) \($0.1)" }.joined(separator: ", "))
        }
    }
}
