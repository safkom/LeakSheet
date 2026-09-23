import SwiftUI

/// Row for one entry on a content tab (Misc / Music Videos / Released / Stems /
/// Fakes).
///
/// Deliberately identical to `SongRowView` in every visual respect, and composed
/// from the same shared pieces: it can't *be* SongRowView, which requires a `Song`,
/// so it differs only where the underlying data does.
struct MiscEntryRowView: View {
    let entry: MiscEntry
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    /// Era cover for this entry's era, matched by the list. Playback and
    /// favourites both key on it, so it is the screen's value — never the
    /// player's, which is whatever is playing right now.
    let eraArt: String?
    /// Play this entry inside its visible list, so auto-advance continues —
    /// the content-tab equivalent of the era/search playback context.
    var onPlay: ((SongVersion) -> Void)?
    var onShowDescription: (DescriptionSheet.Payload) -> Void
    /// Non-audio links (image / video / archive / embed) route up to the list,
    /// which owns the Safari and embed-player sheets.
    var onSelectLink: ((MiscLink) -> Void)?

    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    /// Computed ONCE per row: `entry.mediaLinks` classifies every link (URL parses) and
    /// `asSongVersion` rebuilds on each access, on tabs of ~1,900 entries.
    private let version: SongVersion
    private let previewURL: URL?
    private let hasVideoLink: Bool
    /// Everything that is not the audio stream the row already plays.
    private let extraLinks: [MiscLink]

    init(
        entry: MiscEntry,
        artistName: String,
        artistSlug: String,
        sourceUrl: String? = nil,
        eraArt: String? = nil,
        onPlay: ((SongVersion) -> Void)? = nil,
        onShowDescription: @escaping (DescriptionSheet.Payload) -> Void,
        onSelectLink: ((MiscLink) -> Void)? = nil
    ) {
        self.entry = entry
        self.artistName = artistName
        self.artistSlug = artistSlug
        self.sourceUrl = sourceUrl
        self.eraArt = eraArt
        self.onPlay = onPlay
        self.onShowDescription = onShowDescription
        self.onSelectLink = onSelectLink
        self.version = entry.asSongVersion
        let links = entry.mediaLinks
        self.previewURL = entry.previewImageURL.flatMap(URL.init(string:))
        self.hasVideoLink = links.contains { $0.kind == .video }
        self.extraLinks = links.filter { $0.kind != .stream }
    }

    private var isPlaying: Bool {
        player.isNowPlaying(version, inEra: entry.eraName)
    }

    private var canStream: Bool { version.isStreamable }

    /// Date, length and streaming state on one secondary line, in the slot (and
    /// style) the song row gives its "also known as" line.
    private var metaLine: String? {
        var parts: [String] = []
        if let date = entry.date, !date.isEmpty, date.lowercased() != "n/a" {
            parts.append(date)
        }
        if let length = entry.length, !length.isEmpty, length.lowercased() != "n/a" {
            parts.append(length)
        }
        if entry.streaming == true { parts.append("Streaming") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    var body: some View {
        HStack(spacing: 8) {
            leadingIcon

            VStack(alignment: .leading, spacing: 3) {
                Text(entry.name)
                    .font(.subheadline)
                    .foregroundStyle(isPlaying ? Color.lsAccent : .primary)
                    .fixedSize(horizontal: false, vertical: true)

                if let metaLine {
                    Text(metaLine)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }

                // One flowing pill row, the same capsules a song row shows; the type column
                // ("Music Video") rides along as another pill.
                FlowLayout(spacing: 5) {
                    if let type = entry.entryType, !type.isEmpty {
                        BadgePill(text: type, variant: .entryType, accessibilityPrefix: "Type")
                    }
                    DedupedBadgePills(quality: entry.quality, availability: entry.available)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            ThreeDotMenu(
                version: version, song: nil,
                artistName: artistName, artistSlug: artistSlug,
                sourceUrl: sourceUrl, eraName: entry.eraName, eraArt: eraArt,
                onPlay: onPlay, onShowDescription: onShowDescription,
                extraLinks: extraLinks, onSelectLink: onSelectLink
            )
        }
        .padding(.vertical, 6)
        .padding(.leading, 4)
        .padding(.trailing, 2)
        .background(isPlaying ? Color.lsAccent.opacity(0.08) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .rowHoverHighlight()
        .swipeActions(edge: .trailing) {
            Button {
                favourites.toggleFromVersion(
                    version: version, artistSlug: artistSlug,
                    artistName: artistName, sourceUrl: sourceUrl,
                    eraName: entry.eraName, eraArt: eraArt
                )
                Haptics.light()
            } label: {
                Image(systemName: isFavourited ? "heart.fill" : "heart")
            }
            .tint(.pink)
            .accessibilityLabel(
                isFavourited
                    ? "Remove \(entry.name) from favourites"
                    : "Add \(entry.name) to favourites"
            )

            if canStream {
                Button {
                    player.addToQueue(
                        version, artistName: artistName,
                        eraName: entry.eraName, artUrl: eraArt ?? "", artistSlug: artistSlug
                    )
                    Haptics.light()
                } label: {
                    Image(systemName: "text.append")
                }
                .tint(.lsAccent)
                .accessibilityLabel("Add \(entry.name) to queue")
            }
        }
        .swipeActions(edge: .leading) {
            if canStream {
                Button(action: play) {
                    Image(systemName: "play.fill")
                }
                .tint(.green)
                .accessibilityLabel("Play \(entry.name)")
            }
        }
        .contextMenu {
            SongContextMenu(
                version: version, song: nil,
                artistName: artistName, artistSlug: artistSlug,
                sourceUrl: sourceUrl, eraName: entry.eraName, eraArt: eraArt,
                onPlay: onPlay, onShowDescription: onShowDescription,
                extraLinks: extraLinks, onSelectLink: onSelectLink
            )
        }
        .accessibilityElement(children: .combine)
    }

    private var isFavourited: Bool {
        favourites.isFavouritedByVersion(
            version, artistSlug: artistSlug, eraName: entry.eraName
        )
    }

    // MARK: - Leading slot

    /// The same leading slot as a song row: what is playing, else a play
    /// button for a streamable entry, else the entry's media preview.
    @ViewBuilder
    private var leadingIcon: some View {
        if let previewURL, !isPlaying, !canStream {
            thumbnail(url: previewURL)
                .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
        } else {
            SongPlayControl(
                isCurrent: isPlaying,
                isLoading: player.loading,
                isPlaying: player.isPlaying,
                canStream: canStream,
                title: entry.name,
                play: play
            )
        }
    }

    private func play() {
        guard canStream else { return }
        Haptics.light()
        if let onPlay {
            onPlay(version)
        } else {
            player.playTrack(
                version, artistName: artistName,
                eraName: entry.eraName, artUrl: eraArt ?? "", artistSlug: artistSlug
            )
        }
    }

    /// Through the proxy like every other CachedImage call site: backend downscale,
    /// 429/Retry-After handling, and no hotlink blocking.
    private func thumbnail(url: URL) -> some View {
        CachedImage(
            url: APIClient.shared.imageProxyURL(for: url.absoluteString, width: 64) ?? url,
            maxPixelSize: 64
        ) {
            ArtworkPlaceholder(cornerRadius: 4)
        }
        .frame(width: 24, height: 24)
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .overlay(alignment: .bottomTrailing) {
            // Video thumbnails come from a still frame — badge them so it
            // reads as playable, not just a photo.
            if hasVideoLink {
                Image(systemName: "play.fill")
                    .font(.system(size: 6))
                    .foregroundStyle(.white)
                    .padding(2)
                    .background(.black.opacity(0.55), in: Circle())
            }
        }
        .accessibilityHidden(true)
    }
}
