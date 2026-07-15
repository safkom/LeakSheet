import SwiftUI

/// Explore trackers panel — loads the tracker list from the backend
/// /trackers endpoint (TrackerHub sheet).
struct BrowseArtistsView: View {
    /// Called with (url, curated artist name) — the name overrides the
    /// backend's sheet-title inference, which trips on joke tracker titles.
    var onPick: (String, String?) -> Void

    @State private var artists: [DiscoveryArtist] = []
    @State private var searchText = ""
    @State private var loading = false
    @State private var error: String?
    @State private var loadingUrl = ""

    private var filtered: [DiscoveryArtist] {
        let q = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return artists }
        return artists.filter { $0.name.lowercased().contains(q) }
    }

    var body: some View {
        NavigationStack {
            Group {
                if loading && artists.isEmpty {
                    VStack(spacing: 12) {
                        ProgressView()
                        Text("Loading artists...")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if let error {
                    ContentUnavailableView(
                        "Failed to Load",
                        systemImage: "wifi.exclamationmark",
                        description: Text(error)
                    )
                } else {
                    List {
                        ForEach(filtered) { artist in
                            Button {
                                loadingUrl = artist.url
                                onPick(artist.url, artist.name)
                            } label: {
                                HStack(spacing: 12) {
                                    // Initials
                                    Text(initials(artist.name))
                                        .font(.caption.bold())
                                        .foregroundStyle(.secondary)
                                        .frame(width: 36, height: 36)
                                        .background(Color.lsCard)
                                        .clipShape(RoundedRectangle(cornerRadius: 8))

                                    VStack(alignment: .leading, spacing: 2) {
                                        HStack(spacing: 6) {
                                            Text(artist.name)
                                                .font(.subheadline.weight(.medium))
                                                .foregroundStyle(.primary)
                                                .lineLimit(1)
                                            if artist.best == true {
                                                Image(systemName: "star.fill")
                                                    .font(.caption2)
                                                    .foregroundStyle(.yellow)
                                                    .accessibilityLabel("Best of")
                                            }
                                        }
                                        HStack(spacing: 6) {
                                            if let credit = artist.credit, !credit.isEmpty {
                                                Text("by \(credit)")
                                                    .font(.caption2)
                                                    .foregroundStyle(.tertiary)
                                                    .lineLimit(1)
                                            }
                                            if artist.upToDate == false {
                                                Text("outdated")
                                                    .font(.caption2)
                                                    .foregroundStyle(.orange)
                                            }
                                        }
                                    }

                                    Spacer()

                                    if loadingUrl == artist.url {
                                        ProgressView()
                                            .controlSize(.small)
                                    } else {
                                        Image(systemName: "chevron.right")
                                            .font(.caption2)
                                            .foregroundStyle(.tertiary)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                            .listRowBackground(Color.clear)
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .searchable(text: $searchText, prompt: "Search artists...")
                }
            }
            .background(Color.lsBackground)
            .navigationTitle("Explore Trackers")
            .navigationBarTitleDisplayMode(.inline)
        }
        .task { await loadArtists() }
        .onAppear { loadingUrl = "" }
    }

    private func loadArtists() async {
        guard artists.isEmpty else { return }
        loading = true
        error = nil
        defer { loading = false }

        do {
            // Server sorts best-first then by name; re-sort locally so the
            // order survives a backend that doesn't.
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

    private func initials(_ name: String) -> String {
        name.split(separator: " ")
            .prefix(2)
            .compactMap { $0.first.map { String($0).uppercased() } }
            .joined()
    }
}
