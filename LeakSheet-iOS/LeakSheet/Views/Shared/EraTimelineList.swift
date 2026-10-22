import SwiftUI

/// One era's dated events, as the tracker timeline and the era info sheet show them.
struct EraTimelineList: View {
    let events: [TimelineEvent]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(events) { event in
                HStack(alignment: .top, spacing: 10) {
                    Circle()
                        .fill(Color.lsAccent.opacity(0.7))
                        .frame(width: 6, height: 6)
                        .padding(.top, 6)
                        .accessibilityHidden(true)
                    // Above the event, not beside it: tracker dates run from "2009" to
                    // "Dec 8th, 2023 - Mar 12th, 2024", and a fixed column wraps the long ones.
                    VStack(alignment: .leading, spacing: 2) {
                        if Self.hasDate(event.date) {
                            Text(event.date)
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        Text(event.event)
                            .font(.subheadline)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .accessibilityElement(children: .combine)
            }
        }
    }

    /// Trackers write an unknown date as "???" or leave it blank.
    static func hasDate(_ date: String) -> Bool {
        !date.trimmingCharacters(in: CharacterSet.whitespaces.union(CharacterSet(charactersIn: "?"))).isEmpty
    }
}
