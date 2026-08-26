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

    /// Four tiles across leaves ~90pt each, which cannot hold a grouped
    /// five-digit count at accessibility sizes — "9.381" wrapped mid-number
    /// onto two lines and "Snippets" hyphenated. Reflow to 2×2 instead of
    /// shrinking the text the user asked to be large.
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

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
            Group {
                if dynamicTypeSize.isAccessibilitySize {
                    Grid(horizontalSpacing: 8, verticalSpacing: 8) {
                        GridRow {
                            totalItem
                            statItem(value: stats.available, label: "Available", color: .green)
                        }
                        GridRow {
                            statItem(value: stats.snippets, label: "Snippets", color: .orange)
                            statItem(value: stats.fullHQ, label: "Full HQ", color: .lsAccent)
                        }
                    }
                } else {
                    HStack(spacing: 8) {
                        totalItem
                        statItem(value: stats.available, label: "Available", color: .green)
                        statItem(value: stats.snippets, label: "Snippets", color: .orange)
                        statItem(value: stats.fullHQ, label: "Full HQ", color: .lsAccent)
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
        }
    }

    private var totalItem: some View {
        statItem(value: stats.total, label: "Total", color: .secondary,
                 spoken: "\(stats.total) \(unit) total")
    }

    private func statItem(
        value: Int, label: String, color: Color, spoken: String? = nil
    ) -> some View {
        VStack(spacing: 2) {
            // A count must never break across lines: "9.381" split into "9.3"
            // and "81" reads as two different numbers.
            Text(value.formatted())
                .font(.headline.monospacedDigit())
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .glassEffect(.regular, in: .rect(cornerRadius: 10))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken ?? "\(value) \(label)")
    }
}
