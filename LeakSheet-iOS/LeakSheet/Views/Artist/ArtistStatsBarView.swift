import SwiftUI

/// Stats bar showing total / available / snippets / full HQ. Tappable (when
/// `onTap` is set) to open the full `TrackerStats` breakdown.
struct ArtistStatsBarView: View {
    let stats: ArtistViewModel.Stats
    var onTap: (() -> Void)? = nil

    var body: some View {
        if let onTap {
            Button(action: onTap) { barContent }
                .buttonStyle(.plain)
                .accessibilityHint("Shows the full stats breakdown")
        } else {
            barContent
        }
    }

    private var barContent: some View {
        GlassEffectContainer {
            HStack(spacing: 8) {
                statItem(value: stats.total, label: "Total", color: .secondary)
                statItem(value: stats.available, label: "Available", color: .green)
                statItem(value: stats.snippets, label: "Snippets", color: .orange)
                statItem(value: stats.fullHQ, label: "Full HQ", color: .lsAccent)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
        }
    }

    private func statItem(value: Int, label: String, color: Color) -> some View {
        VStack(spacing: 2) {
            Text("\(value)")
                .font(.headline.monospacedDigit())
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .glassEffect(.regular, in: .rect(cornerRadius: 10))
    }
}
