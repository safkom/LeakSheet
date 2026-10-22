import SwiftUI

/// One era's dated events, as the tracker timeline and the era info sheet show them.
struct EraTimelineList: View {
    let events: [TimelineEvent]

    var body: some View {
        ForEach(events) { event in
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
        }
    }
}
