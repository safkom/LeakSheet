import SwiftUI

/// The recents shelf — a header with a Clear action over a list of tracker
/// cards. Shared by the iOS landing screen and the macOS sidebar's Recents pane.
struct RecentTrackersListView: View {
    @Environment(RecentTrackersManager.self) private var recents

    var showsHeader = true
    var onSelect: (RecentTrackersManager.RecentTracker) -> Void

    @State private var showClearConfirm = false

    var body: some View {
        if !recents.trackers.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                if showsHeader {
                    HStack {
                        Text("Recent")
                            .font(.headline)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button("Clear", role: .destructive) {
                            showClearConfirm = true
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                }

                LazyVStack(spacing: 8) {
                    ForEach(recents.trackers) { entry in
                        RecentTrackerCardView(entry: entry) {
                            onSelect(entry)
                        }
                        .rowHoverHighlight()
                        .padding(.horizontal, 20)
                    }
                }
            }
            .confirmationDialog(
                "Clear all \(recents.trackers.count) recent trackers?",
                isPresented: $showClearConfirm,
                titleVisibility: .visible
            ) {
                Button("Clear", role: .destructive) { recents.clearAll() }
                Button("Cancel", role: .cancel) {}
            }
        }
    }
}
