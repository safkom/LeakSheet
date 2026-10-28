import SwiftUI

/// Horizontal shelf of the latest plays. Each entry carries its version snapshot,
/// so tapping one opens its details without loading its tracker.
struct RecentPlaysShelfView: View {
    @AppStorage(ListeningHistory.enabledKey) private var historyEnabled = true
    @State private var showDescription: SongDetailPayload?

    var body: some View {
        let entries = Self.oneTakePerSong(ListeningHistory.shared.recent)
        if historyEnabled, !entries.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text("Recently Played")
                    .font(.headline)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 20)
                ScrollView(.horizontal) {
                    LazyHStack(spacing: 14) {
                        ForEach(entries) { entry in
                            Button { showDetails(entry) } label: { card(entry) }
                                .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 20)
                }
                .scrollIndicators(.hidden)
            }
            .sheet(item: $showDescription) { payload in
                SongDescriptionSheet(payload: payload)
                    .environment(FavouritesManager.shared)
                    .environment(PlayerViewModel.shared)
            }
        }
    }

    private func card(_ entry: ListeningHistory.RecentPlay) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Group {
                if let art = entry.eraArt, let url = APIClient.shared.imageProxyURL(for: art, width: 240) {
                    CachedImage(url: url, maxPixelSize: 240) { ArtworkPlaceholder(cornerRadius: 0).font(.largeTitle) }
                } else {
                    ArtworkPlaceholder(cornerRadius: 0).font(.largeTitle)
                }
            }
            .frame(width: 120, height: 120)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .accessibilityHidden(true)
            Text(entry.version.derivedBaseName)
                .font(.subheadline.weight(.medium))
                .lineLimit(1)
            Text([entry.version.versionTag, entry.artistName].compactMap { $0 }.joined(separator: " · "))
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .frame(width: 120, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Shows details")
    }

    /// An era plays its takes back to back, so V1 and V2 of one song would fill two cards.
    static func oneTakePerSong(_ entries: [ListeningHistory.RecentPlay]) -> [ListeningHistory.RecentPlay] {
        var seen = Set<String>()
        return entries.filter {
            seen.insert("\($0.artistSlug)::\($0.eraName)::\($0.version.derivedBaseName.lowercased())").inserted
        }
    }

    private func showDetails(_ entry: ListeningHistory.RecentPlay) {
        showDescription = SongDetailPayload(
            song: nil, version: entry.version, artistName: entry.artistName,
            artistSlug: entry.artistSlug, eraName: entry.eraName, eraArt: entry.eraArt
        )
    }
}
