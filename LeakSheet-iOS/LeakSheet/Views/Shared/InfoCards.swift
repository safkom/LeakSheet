import SwiftUI

/// Two-column label/value card used by the song and era info sheets.
struct InfoGrid: View {
    /// (label, value) pairs; blank values are dropped and an empty grid draws nothing.
    let items: [(String, String?)]

    private var shown: [(String, String)] {
        items.compactMap { label, val in
            guard let v = val?.trimmingCharacters(in: .whitespaces), !v.isEmpty else { return nil }
            return (label, v)
        }
    }

    var body: some View {
        if !shown.isEmpty {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 10) {
                ForEach(shown, id: \.0) { label, value in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(label)
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.tertiary)
                        Text(value)
                            .font(.subheadline)
                            .foregroundStyle(.primary)
                    }
                }
            }
            .padding(12)
            .background(Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 10))
        }
    }
}

/// A small caption title above a card's content.
struct CardSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            content
        }
    }
}
