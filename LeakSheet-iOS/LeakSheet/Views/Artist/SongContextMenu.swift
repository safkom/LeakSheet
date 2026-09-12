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
    /// Classified links a content-tab entry carries beyond its audio stream —
    /// images, videos, archives, embeds. Songs have none, so this is empty for
    /// them and the section disappears. It lives in the shared menu rather
    /// than in a second trailing control, because a content-tab row is meant
    /// to be indistinguishable from a song row.
    var extraLinks: [MiscLink] = []
    var onSelectLink: ((MiscLink) -> Void)?

    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    private var isFavourited: Bool {
        if let song {
            return favourites.isFavourited(song: song, artistSlug: artistSlug, eraName: eraName)
        }
        return favourites.isFavouritedByVersion(version, artistSlug: artistSlug, eraName: eraName)
    }

    var body: some View {
        if version.isStreamable {
            Button {
                if let onPlay {
                    onPlay(version)
                } else {
                    player.playTrack(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "", artistSlug: artistSlug)
                }
            } label: {
                Label("Play", systemImage: "play.fill")
            }
            Button {
                player.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "", artistSlug: artistSlug)
            } label: {
                Label("Add to Queue", systemImage: "text.append")
            }
        }
        // A payload with no Song is still favouritable — Now Playing, the
        // description sheet opened from the player, and content-tab rows all
        // carry a bare version, and every one of them silently lost the
        // Favourite item.
        Button {
            if let song {
                favourites.toggle(
                    song: song, artistSlug: artistSlug, artistName: artistName,
                    sourceUrl: sourceUrl, eraName: eraName, eraArt: eraArt
                )
            } else {
                favourites.toggleFromVersion(
                    version: version, artistSlug: artistSlug, artistName: artistName,
                    sourceUrl: sourceUrl, eraName: eraName, eraArt: eraArt
                )
            }
        } label: {
            Label(
                isFavourited ? "Unfavourite" : "Favourite",
                systemImage: isFavourited ? "heart.fill" : "heart"
            )
        }
        Button {
            onShowDescription(DescriptionSheet.Payload(
                song: song, version: version,
                artistName: artistName, artistSlug: artistSlug, eraName: eraName, eraArt: eraArt
            ))
        } label: {
            Label("Details", systemImage: "info.circle")
        }
        if let link = version.links?.first {
            Button {
                Pasteboard.copy(link)
            } label: {
                Label("Copy Link", systemImage: "doc.on.doc")
            }
        }
        if let onSelectLink, !extraLinks.isEmpty {
            // SwiftUI.Section explicitly: the app's own `Section` model (an
            // era's song grouping) shadows it in every file that imports both.
            SwiftUI.Section("Links") {
                ForEach(extraLinks) { link in
                    Button {
                        onSelectLink(link)
                    } label: {
                        Label(link.label, systemImage: link.kind.systemImage)
                    }
                }
            }
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
    var extraLinks: [MiscLink] = []
    var onSelectLink: ((MiscLink) -> Void)?

    var body: some View {
        Menu {
            SongContextMenu(
                version: version, song: song,
                artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                eraName: eraName, eraArt: eraArt,
                onPlay: onPlay, onShowDescription: onShowDescription,
                extraLinks: extraLinks, onSelectLink: onSelectLink
            )
        } label: {
            Image(systemName: "ellipsis")
                .font(.body)
                .foregroundStyle(.secondary)
                .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Song options")
    }
}
