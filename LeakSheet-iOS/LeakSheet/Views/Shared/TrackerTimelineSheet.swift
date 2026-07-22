import SwiftUI

/// The tracker's history, era by era — built from each era's `timeline`
/// events (date + note), which the API returns but the app never showed.
/// Eras are already in chronological order, so rendering them in sequence
/// reads as the story of the catalogue.
struct TrackerTimelineSheet: View {
    let artist: Artist
    @Environment(\.dismiss) private var dismiss

    private var erasWithTimeline: [Era] {
        artist.eras.filter { !($0.timeline ?? []).isEmpty }
    }

    var body: some View {
        NavigationStack {
            Group {
                if erasWithTimeline.isEmpty {
                    ContentUnavailableView(
                        "No Timeline",
                        systemImage: "clock",
                        description: Text("This tracker has no dated history.")
                    )
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 22) {
                            ForEach(erasWithTimeline) { era in
                                eraSection(era)
                            }
                        }
                        .padding(.vertical, 16)
                    }
                }
            }
            .background(Color.lsBackground)
            .navigationTitle("Timeline")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func eraSection(_ era: Era) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(era.name)
                .font(.headline)
                .padding(.horizontal, 16)
            ForEach(era.timeline ?? []) { event in
                HStack(alignment: .top, spacing: 10) {
                    Circle()
                        .fill(Color.lsAccent.opacity(0.7))
                        .frame(width: 6, height: 6)
                        .padding(.top, 5)
                    Text(event.date)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .frame(width: 92, alignment: .leading)
                    Text(event.event)
                        .font(.subheadline)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.horizontal, 16)
            }
        }
    }
}
