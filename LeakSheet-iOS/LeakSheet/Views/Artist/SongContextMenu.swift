import SwiftUI

/// Shared context menu items for song/version rows.
struct SongContextMenu: View {
    let version: SongVersion
    let song: Song?
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let eraName: String
    let eraArt: String?
    var onPlay: ((SongVersion) -> Void)?
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    var body: some View {
        if version.isStreamable {
            Button {
                if let onPlay {
                    onPlay(version)
                } else {
                    player.playTrack(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "")
                }
            } label: {
                Label("Play", systemImage: "play.fill")
            }
            Button {
                player.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "")
            } label: {
                Label("Add to Queue", systemImage: "text.append")
            }
        }
        if let song {
            Button {
                favourites.toggle(
                    song: song,
                    artistSlug: artistSlug,
                    artistName: artistName,
                    sourceUrl: sourceUrl,
                    eraName: eraName,
                    eraArt: eraArt
                )
            } label: {
                Label(
                    favourites.isFavourited(artistSlug: artistSlug, eraName: eraName, baseName: song.baseName) ? "Unfavourite" : "Favourite",
                    systemImage: favourites.isFavourited(artistSlug: artistSlug, eraName: eraName, baseName: song.baseName) ? "heart.fill" : "heart"
                )
            }
        }
        Button {
            onShowDescription(DescriptionSheet.Payload(
                song: song, version: version,
                artistName: artistName, artistSlug: artistSlug, eraName: eraName, eraArt: eraArt
            ))
        } label: {
            Label("Details", systemImage: "info.circle")
        }
    }
}

/// Reusable three-dot menu button wrapping SongContextMenu.
struct ThreeDotMenu: View {
    let version: SongVersion
    let song: Song?
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let eraName: String
    let eraArt: String?
    var onPlay: ((SongVersion) -> Void)?
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    var body: some View {
        Menu {
            SongContextMenu(
                version: version, song: song,
                artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                eraName: eraName, eraArt: eraArt,
                onPlay: onPlay, onShowDescription: onShowDescription
            )
        } label: {
            Image(systemName: "ellipsis")
                .font(.body)
                .foregroundStyle(.secondary)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
