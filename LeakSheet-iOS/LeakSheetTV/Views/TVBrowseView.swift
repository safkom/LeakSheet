import SwiftUI

/// Tracker discovery — the same GET /trackers list the phone shows, as a
/// focusable grid. `.searchable` is kept: tvOS renders it as its own full
/// search screen with the on-screen keyboard, so no placement hint applies.
struct TVBrowseView: View {
    @Environment(RecentTrackersManager.self) private var recents

    @State private var artists: [DiscoveryArtist] = []
    @State private var searchText = ""
    @State private var loading = false
    @State private var error: String?
    @State private var loader = TrackerLoader()
    @State private var loadingURL = ""
    @State private var path: [TVRoute] = []

    private var filtered: [DiscoveryArtist] {
        let q = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return artists }
        return artists.filter { $0.name.lowercased().contains(q) }
    }

    private let columns = [GridItem(.adaptive(minimum: 340), spacing: 48)]

    var body: some View {
        NavigationStack(path: $path) {
            content
                .navigationDestination(for: TVRoute.self) { $0.destination }
        }
    }

    private var content: some View {
        Group {
            if loading && artists.isEmpty {
                ProgressView("Loading trackers…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let error {
                ContentUnavailableView {
                    Label("Failed to Load", systemImage: "wifi.exclamationmark")
                } description: {
                    Text(error)
                } actions: {
                    Button("Retry") { Task { await load() } }
                }
            } else {
                ScrollView {
                    if let loadError = loader.error {
                        Text(loadError)
                            .font(.callout)
                            .foregroundStyle(Color.lsError)
                            .padding(.bottom, 12)
                    }
                    LazyVGrid(columns: columns, spacing: 48) {
                        ForEach(filtered) { artist in
                            TVTrackerCardView(
                                title: artist.name,
                                subtitle: artist.credit.map { "by \($0)" },
                                isBest: artist.best == true,
                                isOutdated: artist.upToDate == false,
                                loading: loadingURL == artist.url
                            ) {
                                Task { await open(artist.url, name: artist.name) }
                            }
                        }
                    }
                    .padding(.vertical, 40)
                }
                .searchable(text: $searchText, prompt: "Search trackers…")
                .overlay {
                    if filtered.isEmpty && !searchText.isEmpty {
                        ContentUnavailableView.search(text: searchText)
                    }
                }
            }
        }
        .background(Color.lsBackground)
        .navigationTitle("Browse")
        .task { await load() }
    }

    private func load() async {
        guard artists.isEmpty else { return }
        loading = true
        error = nil
        defer { loading = false }
        do {
            artists = try await APIClient.shared.fetchTrackers()
                .sorted { a, b in
                    if a.best == true && b.best != true { return true }
                    if a.best != true && b.best == true { return false }
                    return a.name.localizedCaseInsensitiveCompare(b.name) == .orderedAscending
                }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func open(_ url: String, name: String?) async {
        loadingURL = url
        defer { loadingURL = "" }
        if let artist = await loader.load(url, artistName: name, recents: recents) {
            path.append(.artist(artist))
        }
    }
}
