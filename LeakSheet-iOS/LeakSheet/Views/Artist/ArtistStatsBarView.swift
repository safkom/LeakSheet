import SwiftUI

/// Total / available / snippets / full HQ as one line of text that wraps at large
/// sizes. Tappable (when `onTap` is set) to open the full `TrackerStats` breakdown.
struct ArtistStatsBarView: View {
    let stats: ArtistViewModel.Stats
    /// What the totals count — "tracks" for the song tree, "entries" for a tab.
    var unit: String = "tracks"
    var onTap: (() -> Void)? = nil

    var body: some View {
        Button { onTap?() } label: {
            HStack(spacing: 6) {
                FlowLayout(spacing: 12) {
                    // The navigation subtitle already gives the track total.
                    if unit != "tracks" {
                        StatText(value: stats.total, label: unit, color: .primary)
                    }
                    StatText(value: stats.available, label: "available", color: .badgeCD)
                    StatText(value: stats.snippets, label: "snippets", color: .badgeSnippet)
                    StatText(value: stats.fullHQ, label: "full HQ", color: .badgeFull)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if onTap != nil {
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }
            }
            .padding(.horizontal, 16)
            .frame(minHeight: Metrics.hitTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(onTap == nil)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "\(stats.total) \(unit), \(stats.available) available, \(stats.snippets) snippets, \(stats.fullHQ) full HQ"
        )
        .accessibilityHint(onTap == nil ? "" : "Shows the full stats breakdown")
        .accessibilityAddTraits(onTap == nil ? [] : .isButton)
    }
}

private struct StatText: View {
    let value: Int
    let label: String
    let color: Color

    var body: some View {
        // A count must never break across lines: "9.381" split into "9.3"
        // and "81" reads as two numbers.
        Text("\(Text(value.formatted()).foregroundStyle(color).fontWeight(.semibold).monospacedDigit()) \(label)")
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize()
    }
}
