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
    @State private var showClearConfirm = false

    /// Set when hosted as a sidebar destination rather than presented as a
    /// sheet — the host supplies the navigation chrome.
    var embedded = false

    private static let emptyHint: String = {
        #if os(macOS)
        "Hover a song and use its ⋯ menu, or right-click it."
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
                                                    // primaryVersion first: new
                                                    // writes leave the flat
                                                    // fields nil (they are the
                                                    // pre-snapshot legacy path),
                                                    // so reading them alone made
                                                    // every recent favourite
                                                    // render a blank badge row.
                                                    DedupedBadgePills(
                                                        quality: entry.primaryVersion?.quality ?? entry.quality,
                                                        availability: entry.primaryVersion?.availableLength ?? entry.availableLength
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
            #if os(iOS)
            .toolbarTitleDisplayMode(.inline)
            #endif
            .sheet(item: $showDescription) { payload in
                SongDescriptionSheet(payload: payload)
                    .environment(FavouritesManager.shared)
                    .environment(PlayerViewModel.shared)
                    .environment(artistVM)
            }
            .confirmationDialog(
                "Remove all \(favourites.entries.count) favourites?",
                isPresented: $showClearConfirm,
                titleVisibility: .visible
            ) {
                Button("Remove All", role: .destructive) { favourites.clearAll() }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This can't be undone.")
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    if !favourites.entries.isEmpty {
                        // Confirmed, and marked .destructive: this sits in the
                        // slot every other sheet uses for Cancel/Done, and
                        // favourites are the only user-authored data the app
                        // holds — everything else re-downloads.
                        Button("Clear All", role: .destructive) {
                            showClearConfirm = true
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
