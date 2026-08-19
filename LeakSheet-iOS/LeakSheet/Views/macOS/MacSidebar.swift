#if os(macOS)
import SwiftUI

/// Source list: the two fixed destinations, then every tracker you have opened.
///
/// Recents used to be its own pane; on the Mac the recents list *is* the sidebar,
/// which is what makes going back to a tracker a single click instead of a
/// re-open. Settings is not here — it lives in the ⌘, Settings scene.
struct MacSidebar: View {
    @Binding var selection: MacSelection?
    @Environment(RecentTrackersManager.self) private var recents

    @State private var showClearConfirm = false

    var body: some View {
        List(selection: $selection) {
            SwiftUI.Section {
                Label("Browse", systemImage: "magnifyingglass")
                    .tag(MacSelection.browse)
                Label("Favourites", systemImage: "heart.fill")
                    .tag(MacSelection.favourites)
            }

            if !recents.trackers.isEmpty {
                SwiftUI.Section("Trackers") {
                    ForEach(recents.trackers) { entry in
                        MacTrackerRow(entry: entry)
                            .tag(MacSelection.tracker(slug: entry.slug))
                            .contextMenu {
                                Button("Remove from Sidebar", role: .destructive) {
                                    remove(entry)
                                }
                            }
                    }
                }
            }
        }
        .navigationSplitViewColumnWidth(min: 200, ideal: 232, max: 320)
        .safeAreaInset(edge: .bottom) {
            if !recents.trackers.isEmpty {
                HStack {
                    Spacer()
                    Button("Clear", role: .destructive) { showClearConfirm = true }
                        .buttonStyle(.plain)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
            }
        }
        .confirmationDialog(
            "Clear all \(recents.trackers.count) trackers from the sidebar?",
            isPresented: $showClearConfirm,
            titleVisibility: .visible
        ) {
            Button("Clear", role: .destructive) {
                for entry in recents.trackers { MacUIState.shared.forget(slug: entry.slug) }
                recents.clearAll()
                if case .tracker = selection { selection = .browse }
            }
            Button("Cancel", role: .cancel) {}
        }
    }

    private func remove(_ entry: RecentTrackersManager.RecentTracker) {
        // Clear the selection first: removing the row the split view is showing
        // leaves the detail column pointed at a slug with no source URL.
        if selection == .tracker(slug: entry.slug) { selection = .browse }
        MacUIState.shared.forget(slug: entry.slug)
        recents.remove(entry)
    }
}

/// One tracker in the source list. Deliberately compact — a sidebar row is a
/// label, not the card the iOS landing screen shows.
private struct MacTrackerRow: View {
    let entry: RecentTrackersManager.RecentTracker

    var body: some View {
        HStack(spacing: 8) {
            Group {
                if let artUrl = entry.artUrl {
                    CachedImage(url: APIClient.shared.imageProxyURL(for: artUrl, width: 128), maxPixelSize: 128) {
                        placeholder
                    }
                } else {
                    placeholder
                }
            }
            .frame(width: 22, height: 22)
            .clipShape(RoundedRectangle(cornerRadius: 4))

            Text(entry.name)
                .lineLimit(1)
                .truncationMode(.tail)
        }
    }

    private var placeholder: some View {
        Text(Format.initials(entry.name))
            .font(.system(size: 9, weight: .bold))
            .foregroundStyle(.secondary)
            .frame(width: 22, height: 22)
            .background(Color.lsCard)
    }
}
#endif
