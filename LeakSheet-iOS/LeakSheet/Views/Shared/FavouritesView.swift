import SwiftUI

/// Favourites panel showing all saved songs grouped by artist/era.
struct FavouritesView: View {
    @Environment(FavouritesManager.self) private var favourites
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss

    @State private var showDescription: DescriptionSheet.Payload?

    var body: some View {
        NavigationStack {
            Group {
                if favourites.entries.isEmpty {
                    ContentUnavailableView(
                        "No Favourites",
                        systemImage: "heart",
                        description: Text("Swipe left on a song and tap the heart to favourite it.")
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
                                                    // Inline quality/availability badges
                                                    HStack(spacing: 4) {
                                                        if let q = entry.quality, !q.isEmpty {
                                                            let variant = qualityVariant(q)
                                                            Text(q)
                                                                .font(.caption2.weight(.medium))
                                                                .padding(.horizontal, 4)
                                                                .padding(.vertical, 1)
                                                                .background(variant.background)
                                                                .foregroundStyle(variant.foreground)
                                                                .clipShape(Capsule())
                                                        }
                                                        if let a = entry.availableLength, !a.isEmpty {
                                                            let variant = availabilityVariant(a)
                                                            Text(a)
                                                                .font(.caption2.weight(.medium))
                                                                .padding(.horizontal, 4)
                                                                .padding(.vertical, 1)
                                                                .background(variant.background)
                                                                .foregroundStyle(variant.foreground)
                                                                .clipShape(Capsule())
                                                        }
                                                    }
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
            .navigationBarTitleDisplayMode(.inline)
            .sheet(item: $showDescription) { payload in
                SongDescriptionSheet(payload: payload)
                    .environment(FavouritesManager.shared)
                    .environment(PlayerViewModel.shared)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if !favourites.entries.isEmpty {
                        Button("Clear All") {
                            favourites.clearAll()
                        }
                        .foregroundStyle(Color.lsError)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationBackground(.ultraThinMaterial)
    }

    private var favArtPlaceholder: some View {
        Image(systemName: "music.note")
            .foregroundStyle(.secondary)
            .frame(width: 40, height: 40)
            .background(Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}
