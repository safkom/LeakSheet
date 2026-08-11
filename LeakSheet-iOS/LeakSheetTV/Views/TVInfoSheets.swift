import SwiftUI

/// Full tracker stats breakdown — the tvOS counterpart of TrackerStatsSheet.
struct TVStatsView: View {
    let artist: Artist
    let stats: ArtistViewModel.Stats

    @Environment(\.dismiss) private var dismiss

    private var rows: [(String, Int)] {
        var out: [(String, Int)] = [
            ("Total versions", stats.total),
            ("Available", stats.available),
            ("Snippets", stats.snippets),
            ("Confirmed", stats.confirmed),
            ("Full HQ", stats.fullHQ),
        ]
        if let t = artist.trackerStats {
            // Every TrackerStats field is optional — a tracker that doesn't
            // publish a given count should show no row rather than a zero.
            let optional: [(String, Int?)] = [
                ("OG files", t.ogFiles),
                ("Stem bounces", t.stemBounces),
                ("Tagged", t.tagged),
                ("Partial", t.partial),
                ("Unavailable", t.unavailable),
                ("Grails", t.grails),
                ("Wanted", t.wanted),
                ("Best of", t.bestOf),
                ("Worst of", t.worstOf),
            ]
            out += optional.compactMap { label, value in
                value.map { (label, $0) }
            }
        }
        return out
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            HStack {
                Text(artist.name)
                    .font(.largeTitle.bold())
                Spacer()
                Button("Done") { dismiss() }
            }
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 380), spacing: 24)], spacing: 20) {
                    ForEach(rows, id: \.0) { label, value in
                        HStack {
                            Text(label)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text("\(value)")
                                .font(.body.monospacedDigit())
                        }
                        .padding(20)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                }
            }
        }
        .padding(60)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.lsBackground)
        .onExitCommand { dismiss() }
    }
}

/// Badge glossary — the tvOS counterpart of BadgeLegendSheet.
struct TVBadgeLegendView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            HStack {
                Text("Badges")
                    .font(.largeTitle.bold())
                Spacer()
                Button("Done") { dismiss() }
            }
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 480), spacing: 24)], spacing: 20) {
                    ForEach(BadgeLogic.badgeGlossary) { term in
                        entryRow(term.emoji, term.name, term.detail)
                    }
                    ForEach(BadgeLogic.qualityGlossary) { term in
                        entryRow(nil, term.name, term.detail)
                    }
                    ForEach(BadgeLogic.availabilityGlossary) { term in
                        entryRow(nil, term.name, term.detail)
                    }
                }
            }
        }
        .padding(60)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.lsBackground)
        .onExitCommand { dismiss() }
    }

    private func entryRow(_ emoji: String?, _ name: String, _ detail: String) -> some View {
        HStack(spacing: 18) {
            Text(emoji.map { "\($0) \(name)" } ?? name)
                .font(.title3)
                .frame(width: 260, alignment: .leading)
            Text(detail)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(20)
        .background(Color.lsCard)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}
