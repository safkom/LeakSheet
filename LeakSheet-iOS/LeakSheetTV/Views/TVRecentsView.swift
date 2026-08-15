import SwiftUI

/// Recently opened trackers, as a focusable shelf. Reads the same
/// RecentTrackersManager store the phone writes.
struct TVRecentsView: View {
    @Environment(RecentTrackersManager.self) private var recents

    @State private var loader = TrackerLoader()
    @State private var loadingURL = ""
    @State private var path: [TVRoute] = []
    @State private var showClearConfirm = false

    private let columns = [GridItem(.adaptive(minimum: 340), spacing: 48)]

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if recents.trackers.isEmpty {
                    ContentUnavailableView(
                        "No Recent Trackers",
                        systemImage: "clock",
                        description: Text("Trackers you open show up here.")
                    )
                } else {
                    ScrollView {
                        if let error = loader.error {
                            Text(error)
                                .font(.callout)
                                .foregroundStyle(Color.lsError)
                                .padding(.bottom, 12)
                        }
                        LazyVGrid(columns: columns, spacing: 48) {
                            ForEach(recents.trackers) { entry in
                                card(for: entry)
                            }
                        }
                        .padding(.vertical, 40)
                    }
                }
            }
            .background(Color.lsBackground)
            .navigationTitle("Recents")
            .toolbar {
                if !recents.trackers.isEmpty {
                    ToolbarItem(placement: .primaryAction) {
                        Button("Clear", role: .destructive) { showClearConfirm = true }
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
            .navigationDestination(for: TVRoute.self) { $0.destination }
        }
    }

    /// Extracted from the grid body: inlining the art-URL chain pushed the
    /// expression past the type-checker's budget.
    private func card(for entry: RecentTrackersManager.RecentTracker) -> some View {
        let art: URL? = entry.artUrl.flatMap {
            APIClient.shared.imageProxyURL(for: $0, width: 640)
        }
        return TVTrackerCardView(
            title: entry.name,
            detail: "\(entry.totalVersions) tracks",
            artURL: art,
            loading: loadingURL == entry.sourceUrl
        ) {
            Task { await open(entry.sourceUrl) }
        }
    }

    private func open(_ url: String) async {
        loadingURL = url
        defer { loadingURL = "" }
        if let artist = await loader.load(url, recents: recents) {
            path.append(.artist(artist))
        }
    }
}
