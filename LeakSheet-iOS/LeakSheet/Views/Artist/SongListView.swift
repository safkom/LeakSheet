import SwiftUI

/// Renders songs within an era — handles sections and flat lists.
struct SongListView: View {
    let era: Era
    let sections: [Section]
    let songs: [Song]
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    var eraColor: Color?
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    @State private var expandedSongs: Set<String> = []

    /// All streamable versions in the era — set as era context when play is triggered.
    private var allStreamableVersions: [SongVersion] {
        songs.flatMap(\.versions).filter(\.isStreamable)
    }

    private func playWithEraContext(_ version: SongVersion) {
        PlayerViewModel.shared.setEraSongs(eraName: era.name, artistName: artistName, artUrl: era.artUrl ?? "", versions: allStreamableVersions)
        PlayerViewModel.shared.playTrack(version, artistName: artistName, eraName: era.name, artUrl: era.artUrl ?? "")
    }

    var body: some View {
        VStack(spacing: 0) {
            if sections.isEmpty {
                // Flat song list
                ForEach(songs) { song in
                    songRows(song: song)
                }
            } else {
                // Sectioned
                ForEach(sections) { section in
                    if let group = section.group {
                        Text(group)
                            .font(.footnote.weight(.bold))
                            .foregroundStyle(.secondary)
                            .textCase(.uppercase)
                            .padding(.top, 14)
                            .padding(.horizontal, 12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    if !section.name.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(section.name)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(eraColor ?? .secondary)
                                .textCase(.uppercase)
                                .tracking(0.5)
                                .padding(.horizontal, 12)
                                .frame(maxWidth: .infinity, alignment: .leading)

                            Rectangle()
                                .fill((eraColor ?? Color.lsBorder).opacity(0.3))
                                .frame(height: 1)
                                .padding(.horizontal, 12)
                        }
                        .padding(.top, section.group == nil ? 14 : 6)
                    }

                    ForEach(section.songs) { song in
                        songRows(song: song)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func songRows(song: Song) -> some View {
        let isExpanded = expandedSongs.contains(song.baseName)
        let hasMultiple = song.versions.count > 1

        SongRowView(
            song: song,
            version: song.versions.first,
            artistName: artistName,
            artistSlug: artistSlug,
            sourceUrl: sourceUrl,
            eraName: era.name,
            eraArt: era.artUrl,
            onPlay: playWithEraContext,
            onShowDescription: onShowDescription
        )
        .contentShape(Rectangle())
        .accessibilityAddTraits(.isButton)
        .onTapGesture {
            if hasMultiple {
                withAnimation(.easeInOut(duration: 0.2)) {
                    if isExpanded {
                        expandedSongs.remove(song.baseName)
                    } else {
                        expandedSongs.insert(song.baseName)
                    }
                }
            } else if let v = song.versions.first {
                if v.isStreamable {
                    Haptics.light()
                    playWithEraContext(v)
                } else {
                    onShowDescription(DescriptionSheet.Payload(
                        song: song, version: v,
                        artistName: artistName, artistSlug: artistSlug, eraName: era.name, eraArt: era.artUrl
                    ))
                }
            }
        }

        // Expanded versions
        if isExpanded && hasMultiple {
            ForEach(Array(song.versions.enumerated()), id: \.offset) { _, version in
                VersionRowView(
                    version: version,
                    artistName: artistName,
                    artistSlug: artistSlug,
                    sourceUrl: sourceUrl,
                    eraName: era.name,
                    eraArt: era.artUrl,
                    onPlay: playWithEraContext,
                    onShowDescription: onShowDescription
                )
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}
