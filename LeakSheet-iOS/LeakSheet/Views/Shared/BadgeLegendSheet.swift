import SwiftUI

/// A glossary of the quality / availability / badge vocabulary a tracker uses.
/// The terms ("Stem Bounce", "OG File", …) are opaque to newcomers — this
/// makes the color-coded pills legible without prior knowledge.
struct BadgeLegendSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                SwiftUI.Section("Quality") {
                    ForEach(BadgeLogic.qualityGlossary) { swatchRow($0.name, $0.detail, color: qualityVariant($0.name).color) }
                }
                SwiftUI.Section("Availability") {
                    ForEach(BadgeLogic.availabilityGlossary) { swatchRow($0.name, $0.detail, color: availabilityVariant($0.name).color) }
                }
                SwiftUI.Section("Badges") {
                    ForEach(BadgeLogic.badgeGlossary) { term in
                        badgeRow(term.badge.emoji, term.name, term.detail)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.lsBackground)
            .navigationTitle("Legend")
            .toolbarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func swatchRow(_ name: String, _ detail: String, color: Color) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Circle()
                .fill(color)
                .frame(width: 14, height: 14)
                .frame(width: 24, alignment: .center)
            textPair(name, detail)
        }
        .padding(.vertical, 2)
        .listRowBackground(Color.lsCard)
    }

    private func badgeRow(_ emoji: String, _ name: String, _ detail: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(emoji)
                .font(.title3)
                .frame(width: 24, alignment: .center)
            textPair(name, detail)
        }
        .padding(.vertical, 2)
        .listRowBackground(Color.lsCard)
    }

    private func textPair(_ name: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(name)
                .font(.subheadline.weight(.medium))
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
