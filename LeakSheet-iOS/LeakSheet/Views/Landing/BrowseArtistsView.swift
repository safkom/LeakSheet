import SwiftUI

/// Browse artists panel — loads from discovery NDJSON endpoint.
struct BrowseArtistsView: View {
    var onPick: (String) -> Void

    @State private var artists: [DiscoveryArtist] = []
    @State private var searchText = ""
    @State private var loading = false
    @State private var error: String?
    @State private var loadingUrl = ""

    private static let discoveryURL = "https://assets.artistgrid.cx/artists.ndjson"

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
                                onPick(artist.url)
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
                                        if let credit = artist.credit, !credit.isEmpty {
                                            Text("by \(credit)")
                                                .font(.caption2)
                                                .foregroundStyle(.tertiary)
                                                .lineLimit(1)
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
            .navigationTitle("Browse Artists")
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

        guard let url = URL(string: Self.discoveryURL) else {
            error = "Invalid discovery URL"
            return
        }

        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let text = String(data: data, encoding: .utf8) ?? ""
            let decoder = JSONDecoder()
            let parsed: [DiscoveryArtist] = text
                .split(separator: "\n")
                .compactMap { line in
                    try? decoder.decode(DiscoveryArtist.self, from: Data(line.utf8))
                }
                .sorted { a, b in
                    if a.best == true && b.best != true { return true }
                    if a.best != true && b.best == true { return false }
                    return a.name.localizedCaseInsensitiveCompare(b.name) == .orderedAscending
                }
            artists = parsed
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
