import SwiftUI

/// Favourites panel showing all saved songs grouped by artist/era.
struct FavouritesView: View {
    @Environment(FavouritesManager.self) private var favourites
    /// Forwarded into the description sheet so a favourite of the open tracker
    /// resolves its full song (Versions picker, alt title, song-level credits)
    /// instead of showing only the one version the entry stored.
    @Environment(ArtistViewModel.self) private var artistVM: ArtistViewModel?
    @Environment(\.dismiss) private var dismiss

    @State private var showDescription: DescriptionSheet.Payload?

    /// Set when hosted as a sidebar destination rather than presented as a
    /// sheet — the host supplies the navigation chrome.
    var embedded = false

    private static let emptyHint: String = {
        #if os(macOS)
        "Right-click a song and choose Favourite to save it here."
        #else
        "Swipe left on a song and tap the heart to favourite it."
        #endif
    }()

    var body: some View {
        if embedded {
            content
        } else {
            NavigationStack { content }
                .presentationBackground(.ultraThinMaterial)
        }
    }

    private var content: some View {
            Group {
                if favourites.entries.isEmpty {
                    ContentUnavailableView(
                        "No Favourites",
                        systemImage: "heart",
                        description: Text(Self.emptyHint)
                    )
                } else {
                    List {
                        let grouped = favourites.grouped()
                        ForEach(grouped, id: \.artistSlug) { artistGroup in
                            SwiftUI.Section {
                                ForEach(artistGroup.eras, id: \.eraName) { eraGroup in
                                    ForEach(eraGroup.entries) { entry in
                                        Button {
                                            if let payload = entry.toDescriptionPayload {
                                                showDescription = payload
                                            }
                                        } label: {
                                            HStack(spacing: 10) {
                                                // Era art thumbnail
                                                if let artStr = entry.eraArt, !artStr.isEmpty {
                                                    CachedImage(url: APIClient.shared.imageProxyURL(for: artStr, width: 128), maxPixelSize: 128) {
                                                        favArtPlaceholder
                                                    }
                                                    .frame(width: 40, height: 40)
                                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                                } else {
                                                    favArtPlaceholder
                                                        .frame(width: 40, height: 40)
                                                }

                                                VStack(alignment: .leading, spacing: 3) {
                                                    HStack(spacing: 4) {
                                                        if let badge = entry.badge {
                                                            Text(Badge(rawValue: badge)?.emoji ?? "")
                                                                .font(.caption)
                                                        }
                                                        Text(entry.songBaseName)
                                                            .font(.subheadline)
                                                            .foregroundStyle(.primary)
                                                            .lineLimit(1)
                                                    }
                                                    Text(eraGroup.eraName)
                                                        .font(.caption2)
                                                        .foregroundStyle(.secondary)
                                                        .lineLimit(1)
                                                    DedupedBadgePills(
                                                        quality: entry.quality,
                                                        availability: entry.availableLength
                                                    )
                                                }
                                                Spacer()
                                                if entry.toSongVersion != nil {
                                                    Image(systemName: "play.circle")
                                                        .font(.caption)
                                                        .foregroundStyle(.secondary)
                                                        .accessibilityHidden(true)
                                                }
                                                Text("\(entry.songVersionCount)v")
                                                    .font(.caption2.monospacedDigit())
                                                    .foregroundStyle(.secondary)
                                            }
                                            .contentShape(Rectangle())
                                        }
                                        .buttonStyle(.plain)
                                        .swipeActions(edge: .trailing) {
                                            Button(role: .destructive) {
                                                favourites.remove(key: entry.key)
                                            } label: {
                                                Image(systemName: "heart.slash")
                                            }
                                        }
                                    }
                                }
                            } header: {
                                Text(artistGroup.artistName)
                                    .font(.subheadline.weight(.semibold))
                            }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }
            }
            .background(Color.lsBackground)
            .navigationTitle("Favourites (\(favourites.entries.count))")
            .toolbarTitleDisplayMode(.inline)
            .sheet(item: $showDescription) { payload in
                SongDescriptionSheet(payload: payload)
                    .environment(FavouritesManager.shared)
                    .environment(PlayerViewModel.shared)
                    .environment(artistVM)
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    if !favourites.entries.isEmpty {
                        Button("Clear All") {
                            favourites.clearAll()
                        }
                        .foregroundStyle(Color.lsError)
                    }
                }
                ToolbarItem(placement: .primaryAction) {
                    if !embedded {
                        Button("Done") { dismiss() }
                    }
                }
            }
    }

    private var favArtPlaceholder: some View {
        ArtworkPlaceholder(cornerRadius: 6)
            .frame(width: 40, height: 40)
    }
}
