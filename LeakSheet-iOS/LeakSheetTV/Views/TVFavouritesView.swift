import SwiftUI

/// Favourites, grouped by artist and era. tvOS has neither swipe actions nor
/// context menus, so selecting a row pushes the detail screen and Remove lives
/// there — the same reason the song list has no inline actions.
struct TVFavouritesView: View {
    @Environment(FavouritesManager.self) private var favourites

    @State private var path: [TVRoute] = []

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if favourites.entries.isEmpty {
                    ContentUnavailableView(
                        "No Favourites",
                        systemImage: "heart",
                        description: Text("Open a song and choose Favourite to save it here.")
                    )
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 28) {
                            ForEach(favourites.grouped(), id: \.artistSlug) { artistGroup in
                                VStack(alignment: .leading, spacing: 14) {
                                    Text(artistGroup.artistName)
                                        .font(.title3.weight(.semibold))
                                        .padding(.horizontal, 60)

                                    ForEach(artistGroup.eras, id: \.eraName) { eraGroup in
                                        ForEach(eraGroup.entries) { entry in
                                            row(entry, eraName: eraGroup.eraName)
                                        }
                                    }
                                }
                                // Keeps up/down movement inside one artist
                                // before jumping to the next group.
                                .focusSection()
                            }
                        }
                        .padding(.vertical, 40)
                    }
                }
            }
            .background(Color.lsBackground)
            .navigationTitle("Favourites (\(favourites.entries.count))")
            .toolbar {
                if !favourites.entries.isEmpty {
                    ToolbarItem(placement: .primaryAction) {
                        Button("Clear All", role: .destructive) { favourites.clearAll() }
                    }
                }
            }
            .navigationDestination(for: TVRoute.self) { $0.destination }
        }
    }

    @ViewBuilder
    private func row(_ entry: FavouritesManager.FavouriteEntry, eraName: String) -> some View {
        Button {
            if let payload = entry.toDescriptionPayload {
                path.append(.song(payload))
            }
        } label: {
            HStack(spacing: 16) {
                if let art = entry.eraArt, !art.isEmpty {
                    CachedImage(
                        url: APIClient.shared.imageProxyURL(for: art, width: 128),
                        maxPixelSize: 128
                    ) {
                        ArtworkPlaceholder(cornerRadius: 8)
                    }
                    .frame(width: 72, height: 72)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                } else {
                    ArtworkPlaceholder(cornerRadius: 8)
                        .frame(width: 72, height: 72)
                }

                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        if let badge = entry.badge {
                            Text(Badge(rawValue: badge)?.emoji ?? "")
                        }
                        Text(entry.songBaseName)
                            .lineLimit(1)
                    }
                    Text(eraName)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    DedupedBadgePills(quality: entry.quality, availability: entry.availableLength)
                }

                Spacer()

                if entry.toSongVersion != nil {
                    Image(systemName: "play.circle")
                        .foregroundStyle(.secondary)
                        .accessibilityHidden(true)
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 14)
            .contentShape(Rectangle())
        }
        .buttonStyle(TVRowButtonStyle())
        .padding(.horizontal, 36)
    }
}
