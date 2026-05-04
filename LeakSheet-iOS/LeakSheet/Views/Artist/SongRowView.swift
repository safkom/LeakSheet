import SwiftUI

/// A single song row — shows name, badge, version count, play indicator.
struct SongRowView: View {
    let song: Song
    let version: SongVersion?
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let eraName: String
    let eraArt: String?
    var showVersionBadge: Bool = false
    var onPlay: ((SongVersion) -> Void)? = nil
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    private var isPlaying: Bool {
        guard let v = version, let current = player.currentTrack else { return false }
        return current.name == v.name && current.versionTag == v.versionTag
    }

    private var canStream: Bool {
        version?.isStreamable ?? false
    }

    private var hasMultiple: Bool {
        song.versions.count > 1
    }

    var body: some View {
        HStack(spacing: 10) {
            // Play indicator or badge
            leadingIcon
                .frame(width: 24)

            // Song info — title + inline badges on first line, credits on second
            VStack(alignment: .leading, spacing: 3) {
                // First line: title + version tag when in flat (recents/search) context
                HStack(spacing: 5) {
                    Text(song.baseName)
                        .font(.subheadline)
                        .foregroundStyle(isPlaying ? Color.lsAccent : .primary)
                        .fixedSize(horizontal: false, vertical: true)
                    if showVersionBadge, let tag = version?.versionTag {
                        Text("[\(tag)]")
                            .font(.caption.weight(.bold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }

                // Second line: quality/avail badges (single-version only; multi-version shows on each VersionRowView)
                if (!hasMultiple || showVersionBadge), let v = version {
                    BadgeRowView(version: v)
                }

                // Credits
                if (!hasMultiple || showVersionBadge), let v = version {
                    CreditTagsView(version: v)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // Chevron for multi-version (not in recents/search flat view)
            if hasMultiple && !showVersionBadge {
                Image(systemName: "chevron.right")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            // Three-dot menu: single-version songs, or flat version rows in recents/search
            if !hasMultiple || showVersionBadge {
                songMenu
            }
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .background(isPlaying ? Color.lsAccent.opacity(0.08) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .swipeActions(edge: .trailing) {
            Button {
                if version != nil {
                    favourites.toggle(
                        song: song,
                        artistSlug: artistSlug,
                        artistName: artistName,
                        sourceUrl: sourceUrl,
                        eraName: eraName,
                        eraArt: eraArt
                    )
                    Haptics.light()
                }
            } label: {
                Image(systemName: favourites.isFavourited(artistSlug: artistSlug, eraName: eraName, baseName: song.baseName) ? "heart.fill" : "heart")
            }
            .tint(.pink)

            if canStream {
                Button {
                    if let v = version {
                        player.addToQueue(v, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "")
                        Haptics.light()
                    }
                } label: {
                    Image(systemName: "text.append")
                }
                .tint(.lsAccent)
            }
        }
        .swipeActions(edge: .leading) {
            if canStream, let v = version {
                Button {
                    Haptics.light()
                    if let onPlay {
                        onPlay(v)
                    } else {
                        player.playTrack(v, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "")
                    }
                } label: {
                    Image(systemName: "play.fill")
                }
                .tint(.green)
            }
        }
        .contextMenu {
            contextMenuItems
        }
    }

    // MARK: - Three-dot menu (same as context menu)

    @ViewBuilder
    private var songMenu: some View {
        if let version {
            ThreeDotMenu(
                version: version, song: song,
                artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                eraName: eraName, eraArt: eraArt,
                onPlay: onPlay, onShowDescription: onShowDescription
            )
        }
    }

    @ViewBuilder
    private var contextMenuItems: some View {
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
            } else {
                Image(systemName: player.isPlaying ? "speaker.wave.2.fill" : "pause.fill")
                    .font(.caption)
                    .foregroundStyle(Color.lsAccent)
                    .symbolEffect(.variableColor.iterative, options: .repeating, isActive: player.isPlaying)
            }
        } else if showVersionBadge {
            // In recents/search: show ONLY this version's own badge (no fallthrough to song-level)
            if let b = version?.badge, let badge = Badge(rawValue: b) {
                Text(badge.emoji)
                    .font(.caption)
            } else {
                Color.clear
            }
        } else if let badge = song.computedBadge {
            Text(badge.emoji)
                .font(.caption)
        } else {
            Color.clear
        }
    }
}
