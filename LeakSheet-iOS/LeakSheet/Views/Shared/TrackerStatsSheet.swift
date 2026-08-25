import SwiftUI

/// Full tracker breakdown — the header bar shows four numbers, but the API
/// carries a much richer `TrackerStats`: quality distribution, availability
/// tiers, badge counts, and data-completeness ("help wanted") signals.
struct TrackerStatsSheet: View {
    let stats: TrackerStats
    @Environment(\.dismiss) private var dismiss

    private struct Row: Identifiable {
        let label: String
        let value: Int
        let color: Color
        var id: String { label }
    }

    private var qualityRows: [Row] {
        [
            Row(label: "Lossless", value: stats.lossless ?? 0, color: .badgeLossless),
            Row(label: "CD Quality", value: stats.cdQuality ?? 0, color: .badgeCD),
            Row(label: "High Quality", value: stats.highQuality ?? 0, color: .badgeHQ),
            Row(label: "Recording", value: stats.recordings ?? 0, color: .badgeRec),
            Row(label: "Low Quality", value: stats.lowQuality ?? 0, color: .badgeLQ),
            Row(label: "Not Available", value: stats.notAvailableQuality ?? 0, color: .badgeNA),
        ].filter { $0.value > 0 }
    }

    private var availabilityRows: [Row] {
        [
            Row(label: "OG Files", value: stats.ogFiles ?? 0, color: .badgeOGFile),
            // Trackers use one wording or the other and leave the other at 0,
            // so take whichever is populated. NOT `totalFull ?? full`: the
            // server sends `total_full: 0` rather than omitting it, which
            // decodes as Optional(0), and `??` would never fall through —
            // showing "0" (i.e. hiding the row) for every plain-"Full" sheet.
            // Reading `full` alone was the original bug: Carti reports 862 in
            // totalFull and 0 in full, so the row vanished entirely.
            Row(label: "Full", value: max(stats.totalFull ?? 0, stats.full ?? 0), color: .badgeFull),
            Row(label: "Tagged", value: stats.tagged ?? 0, color: .badgeTagged),
            Row(label: "Partial", value: stats.partial ?? 0, color: .badgePartial),
            Row(label: "Snippets", value: stats.snippets ?? 0, color: .badgeSnippet),
            Row(label: "Stem Bounces", value: stats.stemBounces ?? 0, color: .badgeStem),
            Row(label: "Unavailable", value: stats.unavailable ?? 0, color: .badgeUnavailable),
        ].filter { $0.value > 0 }
    }

    private struct BadgeRow: Identifiable {
        let badge: Badge
        let label: String
        let value: Int
        var id: String { badge.rawValue }
    }

    private var badgeRows: [BadgeRow] {
        [
            BadgeRow(badge: .best, label: Badge.best.label, value: stats.bestOf ?? 0),
            BadgeRow(badge: .special, label: Badge.special.label, value: stats.special ?? 0),
            BadgeRow(badge: .grail, label: "Grails", value: stats.grails ?? 0),
            BadgeRow(badge: .wanted, label: Badge.wanted.label, value: stats.wanted ?? 0),
            BadgeRow(badge: .worst, label: Badge.worst.label, value: stats.worstOf ?? 0),
        ].filter { $0.value > 0 }
    }

    private var missingLinks: Int { stats.missingLinks ?? 0 }
    private var sourcesNeeded: Int { stats.sourcesNeeded ?? 0 }

    var body: some View {
        NavigationStack {
            List {
                if !qualityRows.isEmpty {
                    SwiftUI.Section("Quality") {
                        QualityBar(segments: qualityRows.map { (value: $0.value, color: $0.color) })
                            .listRowBackground(Color.lsCard)
                            .padding(.vertical, 4)
                        ForEach(qualityRows) { statRow($0) }
                    }
                }
                if !availabilityRows.isEmpty {
                    SwiftUI.Section("Availability") {
                        ForEach(availabilityRows) { statRow($0) }
                    }
                }
                if !badgeRows.isEmpty {
                    SwiftUI.Section("Badges") {
                        ForEach(badgeRows) { r in
                            HStack(spacing: 12) {
                                Text(r.badge.emoji).font(.body).frame(width: 24)
                                    .accessibilityHidden(true)
                                Text(r.label).font(.subheadline)
                                Spacer()
                                Text("\(r.value)").font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
                            }
                            .listRowBackground(Color.lsCard)
                        }
                    }
                }
                if missingLinks > 0 || sourcesNeeded > 0 {
                    SwiftUI.Section {
                        if missingLinks > 0 {
                            statRow(Row(label: "Missing links", value: missingLinks, color: .lsError))
                        }
                        if sourcesNeeded > 0 {
                            statRow(Row(label: "Sources needed", value: sourcesNeeded, color: .badgeRec))
                        }
                    } header: {
                        Text("Help wanted")
                    } footer: {
                        Text("Links and sources the community still needs to complete this tracker.")
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.lsBackground)
            .navigationTitle("Stats")
            #if os(iOS)
            .toolbarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func statRow(_ row: Row) -> some View {
        HStack(spacing: 12) {
            Circle().fill(row.color).frame(width: 12, height: 12).frame(width: 24)
                .accessibilityHidden(true)
            Text(row.label).font(.subheadline)
            Spacer()
            Text("\(row.value)").font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
        }
        .listRowBackground(Color.lsCard)
    }
}

/// A single stacked bar showing the relative size of each quality tier.
private struct QualityBar: View {
    let segments: [(value: Int, color: Color)]

    var body: some View {
        let total = max(segments.reduce(0) { $0 + $1.value }, 1)
        GeometryReader { geo in
            HStack(spacing: 1) {
                ForEach(segments.indices, id: \.self) { i in
                    if segments[i].value > 0 {
                        Rectangle()
                            .fill(segments[i].color)
                            .frame(width: max(2, geo.size.width * CGFloat(segments[i].value) / CGFloat(total)))
                    }
                }
            }
        }
        .frame(height: 12)
        .clipShape(Capsule())
    }
}
