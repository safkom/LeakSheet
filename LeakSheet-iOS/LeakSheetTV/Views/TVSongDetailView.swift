import SwiftUI

/// The song detail screen. On iOS this information is split between a
/// description sheet, a swipe action set and a context menu; tvOS has none of
/// those affordances, so it all lands here as explicit focusable buttons.
struct TVSongDetailView: View {
    let payload: SongDetailPayload

    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    @State private var selected: SongVersion
    @State private var qrURL: URL?

    init(payload: SongDetailPayload) {
        self.payload = payload
        _selected = State(initialValue: payload.version)
    }

    private var versions: [SongVersion] {
        payload.song?.versions ?? [payload.version]
    }

    /// Same fallback the iOS detail sheet uses: a payload built from a saved
    /// favourite may have no slug, so derive one from the artist name.
    private var slug: String {
        payload.artistSlug ?? payload.artistName.slugified
    }

    private var isFavourite: Bool {
        favourites.isFavouritedByVersion(selected, artistSlug: slug, eraName: payload.eraName)
    }

    var body: some View {
        ScrollView {
            HStack(alignment: .top, spacing: 48) {
                artwork
                VStack(alignment: .leading, spacing: 24) {
                    titleBlock
                    actions
                    if versions.count > 1 { versionPicker }
                    metadata
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(60)
        }
        .background(Color.lsBackground)
        .navigationTitle(payload.song?.baseName ?? payload.version.name)
        .sheet(item: $qrURL) { QRCodeSheet(url: $0, title: selected.name) }
    }

    // MARK: - Pieces

    @ViewBuilder
    private var artwork: some View {
        Group {
            if let art = payload.eraArt,
               let url = APIClient.shared.imageProxyURL(for: art, width: 640) {
                CachedImage(url: url, maxPixelSize: 640) {
                    ArtworkPlaceholder(cornerRadius: 16)
                }
                .aspectRatio(contentMode: .fill)
            } else {
                ArtworkPlaceholder(cornerRadius: 16)
            }
        }
        .frame(width: 420, height: 420)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private var titleBlock: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(selected.name)
                .font(.largeTitle.bold())
                .lineLimit(3)
            Text("\(payload.artistName) · \(payload.eraName)")
                .font(.title3)
                .foregroundStyle(.secondary)
            BadgeRowView(version: selected)
            CreditTagsView(version: selected)
        }
    }

    private var actions: some View {
        HStack(spacing: 16) {
            Button {
                player.playInEra(
                    selected,
                    eraName: payload.eraName,
                    artistName: payload.artistName,
                    artUrl: payload.eraArt ?? "",
                    versions: versions.filter(\.isStreamable),
                    artistSlug: payload.artistSlug
                )
            } label: {
                Label("Play", systemImage: "play.fill")
            }
            .disabled(!selected.isStreamable)

            Button {
                player.addToQueue(
                    selected,
                    artistName: payload.artistName,
                    eraName: payload.eraName,
                    artUrl: payload.eraArt ?? "",
                    artistSlug: payload.artistSlug ?? ""
                )
            } label: {
                Label("Queue", systemImage: "text.append")
            }
            .disabled(!selected.isStreamable)

            Button {
                favourites.toggleFromVersion(
                    version: selected,
                    artistSlug: slug,
                    artistName: payload.artistName,
                    sourceUrl: nil,
                    eraName: payload.eraName,
                    eraArt: payload.eraArt
                )
            } label: {
                Label(
                    isFavourite ? "Favourited" : "Favourite",
                    systemImage: isFavourite ? "heart.fill" : "heart"
                )
            }

            // No browser and no WebKit on tvOS — links hand off by QR instead
            // of being dead controls.
            if let link = selected.links?.first, let url = URL(string: link) {
                Button {
                    qrURL = url
                } label: {
                    Label("Open on phone", systemImage: "qrcode")
                }
            }
        }
        .focusSection()
    }

    private var versionPicker: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Versions")
                .font(.headline)
                .foregroundStyle(.secondary)
            ScrollView(.horizontal) {
                HStack(spacing: 14) {
                    ForEach(Array(versions.enumerated()), id: \.offset) { _, version in
                        Button {
                            selected = version
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(version.versionTag ?? version.name)
                                    .lineLimit(1)
                                BadgeRowView(version: version)
                            }
                            .frame(width: 240, alignment: .leading)
                            .padding(16)
                            .background(version.id == selected.id ? Color.lsPrimary.opacity(0.25) : Color.lsCard)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.vertical, 6)
            }
            .scrollClipDisabled()
            .focusSection()
        }
    }

    @ViewBuilder
    private var metadata: some View {
        let rows: [(String, String)] = [
            ("Quality", selected.quality),
            ("Available", selected.availableLength),
            ("Length", selected.trackLength),
            ("Leak date", selected.leakDate),
            ("File date", selected.fileDate),
            ("Type", selected.type),
        ].compactMap { label, value in
            guard let value, !value.isEmpty else { return nil }
            return (label, value)
        }

        if !rows.isEmpty || !(selected.notes ?? "").isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(rows, id: \.0) { label, value in
                    HStack(alignment: .top, spacing: 20) {
                        Text(label)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .frame(width: 200, alignment: .leading)
                        Text(value)
                            .font(.callout)
                    }
                }
                if let notes = selected.notes, !notes.isEmpty {
                    Text(notes)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .padding(.top, 8)
                }
            }
        }
    }
}
