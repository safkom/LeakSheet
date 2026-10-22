import SwiftUI

/// The tracker's history, era by era, from each era's `timeline` events (date +
/// note). Eras are already chronological, so they render in sequence.
struct TrackerTimelineSheet: View {
    let artist: Artist
    @Environment(\.dismiss) private var dismiss

    /// Each era's events, minus ones an earlier era already listed: trackers repeat the
    /// event that ends one era ("X releases") as the first event of the next.
    static func sections(_ eras: [Era]) -> [(era: Era, events: [TimelineEvent])] {
        var seen = Set<String>()
        return eras.compactMap { era in
            let events = (era.timeline ?? []).filter { seen.insert($0.id).inserted }
            return events.isEmpty ? nil : (era, events)
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                let sections = Self.sections(artist.eras)
                if sections.isEmpty {
                    ContentUnavailableView(
                        "No Timeline",
                        systemImage: "clock",
                        description: Text("This tracker has no dated history.")
                    )
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 22) {
                            ForEach(sections, id: \.era.id) { section in
                                eraSection(section.era, section.events)
                            }
                        }
                        .padding(.vertical, 16)
                    }
                }
            }
            .background(Color.lsBackground)
            .navigationTitle("Timeline")
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

    private func eraSection(_ era: Era, _ events: [TimelineEvent]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(era.name)
                .font(.headline)
                .padding(.horizontal, 16)
            EraTimelineList(events: events)
                .padding(.horizontal, 16)
        }
    }
}
