import SwiftUI

/// Two-column label/value card used by the song and era info sheets.
struct InfoGrid: View {
    /// (label, value) pairs; blank values are dropped and an empty grid draws nothing.
    let items: [(String, String?)]

    private var shown: [(String, String)] {
        items.compactMap { label, val in
            guard let value = val?.trimmingCharacters(in: .whitespaces), !value.isEmpty else { return nil }
            return (label, value)
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

/// Big-number tiles in an adaptive grid, for counts read at a glance.
struct StatGrid: View {
    struct Item: Identifiable {
        let label: String
        let value: Int
        var tint: Color = .primary
        var id: String { label }
    }

    let items: [Item]
    var minWidth: CGFloat = 96

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: minWidth), spacing: 8)], spacing: 8) {
            ForEach(items) { item in
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.value.formatted())
                        .font(.title2.weight(.bold).monospacedDigit())
                        .foregroundStyle(item.tint)
                    Text(item.label)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
                .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(Color.lsCard)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .accessibilityElement(children: .combine)
            }
        }
    }
}

/// Label and count over a bar sized against the largest row, in one card.
struct BarList: View {
    struct Row: Identifiable {
        let label: String
        let value: Int
        /// Spoken and shown after the number, e.g. "songs".
        var unit: String = ""
        var id: String { label }
    }

    let rows: [Row]
    var tint: Color = .lsAccent

    var body: some View {
        let top = max(rows.map(\.value).max() ?? 1, 1)
        VStack(spacing: 12) {
            ForEach(rows) { row in
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(row.label)
                            .font(.subheadline)
                            .lineLimit(2)
                        Spacer(minLength: 8)
                        Text(row.unit.isEmpty ? row.value.formatted() : "\(row.value.formatted()) \(row.unit)")
                            .font(.subheadline.weight(.semibold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    GeometryReader { geo in
                        Capsule()
                            .fill(tint.opacity(0.85))
                            .frame(width: max(6, geo.size.width * CGFloat(row.value) / CGFloat(top)))
                    }
                    .frame(height: 6)
                    .background(Capsule().fill(Color.primary.opacity(0.06)))
                    .accessibilityHidden(true)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(12)
        .background(Color.lsCard)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
