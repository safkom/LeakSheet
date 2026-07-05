import SwiftUI

/// A specific version row — shown when a multi-version song is expanded.
struct VersionRowView: View {
    let version: SongVersion
    /// Position within the song's version list — fallback label when the
    /// version has no explicit tag, so untagged versions stay tellable apart.
    var versionIndex: Int? = nil
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let eraName: String
    let eraArt: String?
    var onPlay: ((SongVersion) -> Void)? = nil
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    private var isPlaying: Bool {
        guard let current = player.currentTrack else { return false }
        return current.name == version.name && current.versionTag == version.versionTag
    }

    private var canStream: Bool {
        version.isStreamable
    }

    private var versionLabel: String? {
        if let tag = version.versionTag { return "[\(tag)]" }
        if let idx = versionIndex { return "#\(idx + 1)" }
        return nil
    }

    var body: some View {
        HStack(spacing: 8) {
            // Version tag (indented, no vertical line); untagged versions
            // fall back to their list position so rows remain identifiable.
            if let label = versionLabel {
                Text(label)
                    .font(.caption.weight(.bold).monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(width: 40, alignment: .center)
                    .accessibilityLabel("Version \(label)")
            } else {
                Spacer().frame(width: 40)
            }

            // Version info — name + inline badges on first line, credits on second
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    if let b = version.badge, let badge = Badge(rawValue: b) {
                        Text(badge.emoji)
                            .font(.caption)
                    }
                    BadgeRowView(version: version)
                }
                CreditTagsView(version: version)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // Three-dot menu
            versionMenu
        }
        .padding(.vertical, 4)
        .padding(.leading, 36)
        .padding(.trailing, 12)
        .background(isPlaying ? Color.lsAccent.opacity(0.06) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
        .accessibilityAddTraits(.isButton)
        .onTapGesture {
            if canStream {
                Haptics.light()
                if let onPlay {
                    onPlay(version)
                } else {
                    player.playTrack(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "")
                }
            } else {
                onShowDescription(DescriptionSheet.Payload(
                    song: nil, version: version,
                    artistName: artistName, artistSlug: artistSlug, eraName: eraName, eraArt: eraArt
                ))
            }
        }
        .swipeActions(edge: .trailing) {
            if canStream {
                Button {
                    player.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "")
                    Haptics.light()
                } label: {
                    Image(systemName: "text.append")
                }
                .tint(.lsAccent)
            }
        }
        .contextMenu {
            contextMenuItems
        }
    }

    // MARK: - Three-dot menu

    private var versionMenu: some View {
        ThreeDotMenu(
            version: version, song: nil,
            artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
            eraName: eraName, eraArt: eraArt,
            onPlay: onPlay, onShowDescription: onShowDescription
        )
    }

    @ViewBuilder
    private var contextMenuItems: some View {
        SongContextMenu(
            version: version, song: nil,
            artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
            eraName: eraName, eraArt: eraArt,
            onPlay: onPlay, onShowDescription: onShowDescription
        )
    }
}
