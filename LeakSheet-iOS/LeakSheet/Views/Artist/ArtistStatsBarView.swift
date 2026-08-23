import SwiftUI

/// Stats bar showing total / available / snippets / full HQ. Tappable (when
/// `onTap` is set) to open the full `TrackerStats` breakdown.
struct ArtistStatsBarView: View {
    let stats: ArtistViewModel.Stats
    /// What the totals count — "tracks" for the song tree, "entries" for a
    /// content tab. Spoken by VoiceOver; the visible tile label stays "Total"
    /// so the four tiles keep a uniform width.
    var unit: String = "tracks"
    var onTap: (() -> Void)? = nil

    var body: some View {
        if let onTap {
            Button(action: onTap) { barContent.contentShape(Rectangle()) }
                .buttonStyle(.plain)
                .accessibilityHint("Shows the full stats breakdown")
        } else {
            barContent
        }
    }

    private var barContent: some View {
        GlassEffectContainer {
            HStack(spacing: 8) {
                statItem(value: stats.total, label: "Total", color: .secondary,
                         spoken: "\(stats.total) \(unit) total")
                statItem(value: stats.available, label: "Available", color: .green)
                statItem(value: stats.snippets, label: "Snippets", color: .orange)
                statItem(value: stats.fullHQ, label: "Full HQ", color: .lsAccent)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
        }
    }

    private func statItem(
        value: Int, label: String, color: Color, spoken: String? = nil
    ) -> some View {
        VStack(spacing: 2) {
            Text(value.formatted())
                .font(.headline.monospacedDigit())
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .glassEffect(.regular, in: .rect(cornerRadius: 10))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken ?? "\(value) \(label)")
    }
}
