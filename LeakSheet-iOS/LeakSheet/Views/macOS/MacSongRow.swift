#if os(macOS)
import SwiftUI

/// A song or version row for the Mac list.
///
/// The iOS row hangs Play / Add to Queue / Favourite off `swipeActions`, a
/// gesture macOS does not have — which left right-click and a permanently
/// visible ellipsis button as the only way to do anything. Here: the row shows
/// nothing but content until the pointer is over it, then reveals Play and the
/// menu. Selection, ↑↓, ⏎ and double-click come from the enclosing `List`.
struct MacSongRow: View {
    let song: Song
    let version: SongVersion?
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let eraName: String
    let eraArt: String?
    /// Show the version tag inline — flat lists (search, recents, an expanded
    /// version) name the version; grouped era rows name the song.
    var showVersionBadge = false
    /// Indent for a version nested under its song.
    var indented = false
    var onPlay: ((SongVersion) -> Void)?
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    @State private var hovering = false
    /// `.increased` while this row is the List's selection — see `BadgePill`.
    @Environment(\.backgroundProminence) private var prominence

    private var onProminentBackground: Bool { prominence == .increased }

    /// The now-playing accent, unless the selection fill is already using it.
    private var playingTint: Color { onProminentBackground ? .primary : .lsAccent }

    private var isPlaying: Bool {
        guard let v = version, let current = player.currentTrack else { return false }
        return current.name == v.name && current.versionTag == v.versionTag
    }

    private var canStream: Bool { version?.isStreamable ?? false }
    private var hasMultiple: Bool { song.hasMultipleVersions }

    /// First alternate title that differs from the base name.
    private var akaTitle: String? {
        for v in song.versions {
            if let alt = v.altTitles?.first(where: {
                !$0.isEmpty && $0.caseInsensitiveCompare(song.baseName) != .orderedSame
            }) {
                return alt
            }
        }
        return nil
    }

    var body: some View {
        HStack(spacing: 8) {
            leadingIcon
                .frame(width: 18)

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(song.baseName)
                        .font(.subheadline)
                        // Plain `.primary`, never the accent: SwiftUI inverts a
                        // primary label on a selected row for free, whereas an
                        // accent-tinted title on the accent-filled selection is
                        // blue on blue. `backgroundProminence` is not a reliable
                        // guard here — it reaches BadgePill but not this read —
                        // so the playing state is carried by the leading
                        // speaker glyph alone.
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    if showVersionBadge, let tag = version?.versionTag {
                        Text("[\(tag)]")
                            .font(.caption.weight(.bold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    if let aka = akaTitle, !indented {
                        Text(aka)
                            .font(.caption2)
                            .foregroundStyle(onProminentBackground ? AnyShapeStyle(.secondary) : AnyShapeStyle(.tertiary))
                            .lineLimit(1)
                            .accessibilityLabel("Also known as \(aka)")
                    }
                }

                HStack(spacing: 6) {
                    if (!hasMultiple || showVersionBadge), let v = version {
                        BadgeRowView(version: v)
                    } else if let best = song.bestPlayableVersion {
                        // Collapsed multi-version row: badge the version a play
                        // action would actually reach, not versions.first.
                        BadgeRowView(version: best)
                        Text("\(song.versions.count) versions")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    if (!hasMultiple || showVersionBadge), let v = version {
                        CreditTagsView(version: v)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            trailingControls
        }
        .padding(.vertical, Metrics.rowVerticalPadding)
        .padding(.leading, indented ? 28 : 0)
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
        .contextMenu { menuItems }
    }

    // MARK: - Pieces

    /// Shared by the right-click menu and the hover ellipsis. Nil-version rows
    /// (a song whose every version was filtered out) get no actions.
    @ViewBuilder
    private var menuItems: some View {
        if let v = version {
            SongContextMenu(
                version: v, song: song,
                artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                eraName: eraName, eraArt: eraArt,
                onPlay: onPlay, onShowDescription: onShowDescription
            )
        }
    }

    @ViewBuilder
    private var leadingIcon: some View {
        if isPlaying {
            if player.loading {
                ProgressView()
                    .controlSize(.mini)
                    .tint(playingTint)
            } else {
                Image(systemName: player.isPlaying ? "speaker.wave.2.fill" : "pause.fill")
                    .font(.caption)
                    .foregroundStyle(playingTint)
            }
        } else if showVersionBadge {
            if let b = version?.badge, let badge = Badge(rawValue: b) {
                Text(badge.emoji).font(.caption)
            } else {
                Color.clear
            }
        } else if let badge = song.computedBadge {
            Text(badge.emoji).font(.caption)
        } else {
            Color.clear
        }
    }

    /// Hidden until hover — a Mac list row should be content, not a control bar.
    /// `opacity` rather than `if`: removing the buttons changes the row height
    /// and makes the whole list twitch as the pointer crosses it.
    @ViewBuilder
    private var trailingControls: some View {
        HStack(spacing: 2) {
            if canStream, let v = version {
                Button {
                    play(v)
                } label: {
                    Image(systemName: "play.fill")
                        .font(.caption)
                        .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Play")
                .accessibilityLabel("Play \(song.baseName)")
            }

            if version != nil {
                Menu {
                    menuItems
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.caption)
                        .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                        .contentShape(Rectangle())
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .frame(width: Metrics.hitTarget)
                .accessibilityLabel("Song options")
            }

            if isFavourited {
                Image(systemName: "heart.fill")
                    .font(.caption2)
                    .foregroundStyle(onProminentBackground ? Color.primary : Color.lsFavourite)
                    .accessibilityLabel("Favourited")
            }
        }
        .foregroundStyle(.secondary)
        // The heart is state, not a control — it stays visible.
        .opacity(hovering || isFavourited ? 1 : 0)
    }

    private var isFavourited: Bool {
        favourites.isFavourited(artistSlug: artistSlug, eraName: eraName, baseName: song.baseName)
    }

    private func play(_ v: SongVersion) {
        if let onPlay {
            onPlay(v)
        } else {
            player.playTrack(v, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "", artistSlug: artistSlug)
        }
    }
}
#endif
