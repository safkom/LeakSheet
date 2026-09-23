import SwiftUI

/// Explore trackers panel — loads the tracker list from the backend
/// /trackers endpoint (ArtistGrid registry).
struct BrowseArtistsView: View {
    /// Called with (url, curated artist name) — the name overrides the
    /// backend's sheet-title inference, which trips on joke tracker titles.
    var onPick: (String, String?) -> Void

    /// Set when hosted as a sidebar destination rather than a sheet: the host supplies
    /// the chrome, and a nested NavigationStack would fight it for title, toolbar and search.
    var embedded = false

    @State private var artists: [DiscoveryArtist] = []
    @State private var searchText = ""
    @State private var loading = false
    @State private var error: String?
    @State private var loadingUrl = ""
    @Environment(\.dismiss) private var dismiss

    private var filtered: [DiscoveryArtist] {
        let q = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return artists }
        return artists.filter { $0.name.lowercased().contains(q) }
    }

    var body: some View {
        if embedded {
            content
        } else {
            NavigationStack {
                content
                    .navigationTitle("Explore Trackers")
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
    }

    private var content: some View {
            Group {
                if loading && artists.isEmpty {
                    VStack(spacing: 12) {
                        ProgressView()
                        Text("Loading trackers...")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if let error {
                    ContentUnavailableView {
                        Label("Failed to Load", systemImage: "wifi.exclamationmark")
                    } description: {
                        Text(error)
                    } actions: {
                        // .task doesn't re-run while presented, so without Retry the sheet is stuck on
                        // the error. loadArtists() clears `error` and refetches.
                        Button("Retry") { Task { await loadArtists() } }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    List {
                        ForEach(filtered) { artist in
                            Button {
                                loadingUrl = artist.url
                                onPick(artist.url, artist.name)
                            } label: {
                                HStack(spacing: 12) {
                                    // Initials
                                    Text(Format.initials(artist.name))
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
                                                // .secondary (not .tertiary) clears WCAG AA on OLED black for this text.
                                                Text("by \(credit)")
                                                    .font(.caption2)
                                                    .foregroundStyle(.secondary)
                                                    .lineLimit(1)
                                            }
                                            if artist.upToDate == false {
                                                Text("outdated")
                                                    .font(.caption2)
                                                    .foregroundStyle(.orange)
                                            }
                                            // Link health is tri-state upstream: only a definite false is worth a warning,
                                            // shown BEFORE the user opens a tracker whose files are gone.
                                            if artist.workingLinks == false {
                                                Text("dead links")
                                                    .font(.caption2)
                                                    .foregroundStyle(Color.lsError)
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
                                // Inside the label, not outside the Button (DECISIONS.md::contentShape).
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .listRowBackground(Color.clear)
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    // .task below runs once per process, so pull-to-refresh is how the list picks
                    // up feed changes.
                    .refreshable { await loadArtists(force: true) }
                    // Same placement as the artist screen (ArtistView.swift): `.automatic` puts
                    // the field in the bottom slot on iPhone.
                    #if os(iOS)
                    .searchable(
                        text: $searchText,
                        placement: .navigationBarDrawer(displayMode: .always),
                        prompt: "Search trackers..."
                    )
                    #else
                    .searchable(text: $searchText, prompt: "Search trackers...")
                    #endif
                    .overlay {
                        // Keep the List (and its search field) mounted; show the
                        // no-results state on top when a query matches nothing.
                        if filtered.isEmpty && !searchText.isEmpty {
                            ContentUnavailableView.search(text: searchText)
                        }
                    }
                }
            }
            // Fill the pane: without this the enclosing detail column centres a
            // content-sized block, leaving the URL field floating mid-window.
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.lsBackground)
            .task { await loadArtists() }
            .onAppear { loadingUrl = "" }
    }

    /// `force` is pull-to-refresh: refetch even though a list is showing.
    private func loadArtists(force: Bool = false) async {
        guard force || artists.isEmpty else { return }
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
        } catch where error is CancellationError || (error as? URLError)?.code == .cancelled {
            // The refresh gesture was released or the view went away.
            // URLSession reports cancellation as URLError, not CancellationError.
        } catch {
            // A failed refresh keeps the list already on screen; the error
            // view replaces it only when there was nothing to show.
            if artists.isEmpty {
                self.error = error.localizedDescription
            }
        }
    }

}
