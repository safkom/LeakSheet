import SwiftUI

/// Row for one entry on a content tab (Misc / Music Videos / Released / Stems /
/// Fakes).
///
/// Deliberately identical to `SongRowView` in every visual respect — same
/// leading slot, typography, pill component, secondary line, trailing control,
/// now-playing wash, padding, swipe actions and context menu. It cannot simply
/// *be* SongRowView, which requires a `Song`; a content-tab entry has only a
/// version's worth of data. So it composes the same shared pieces instead, and
/// differs only where the underlying data does.
///
/// It used to look like a different row family: a 44pt thumbnail against the
/// song row's 24pt icon slot, a heavier title, a bespoke pill for the type
/// column, a metadata line of calendar / clock / antenna glyphs, and a
/// trailing icon that looked like a play button but was a bare `Image` — the
/// row's tap opened Details, so nothing happened when you pressed it. There
/// were no swipe actions and no context menu at all, which on the Ye Stems tab
/// left 1,642 streamable entries with no way to play, queue or favourite them
/// short of opening the detail sheet.
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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// Computed ONCE per row, not per access. `entry.mediaLinks` runs
    /// MiscLinkClassifier.classify (a URLComponents parse plus a
    /// StreamResolver.target parse) and label(for:) per link, and this view
    /// read it five times per body evaluation on a tab that can carry ~1,900
    /// entries. `asSongVersion` is likewise rebuilt on every access.
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

    /// Date, length and streaming state on one secondary line.
    ///
    /// Occupies the slot the song row gives its "also known as" line and reads
    /// the same way: caption2, secondary, one line. The old version drew each
    /// value behind its own SF Symbol — a calendar, a clock, an antenna —
    /// which is chrome no song row has.
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
        HStack(spacing: 10) {
            leadingIcon
                .frame(width: 24)

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

                // One flowing pill row, the same capsules a song row shows.
                // The type column ("Music Video", "Freestyle") is data a song
                // row has no equivalent of, so it rides along as another pill
                // rather than as a shape of its own.
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
        .padding(.vertical, Metrics.rowVerticalPadding)
        .padding(.horizontal, Metrics.rowHorizontalPadding)
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
                Button {
                    Haptics.light()
                    if let onPlay {
                        onPlay(version)
                    } else {
                        player.playTrack(
                            version, artistName: artistName,
                            eraName: entry.eraName, artUrl: eraArt ?? "", artistSlug: artistSlug
                        )
                    }
                } label: {
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

    /// The song row's 24pt slot, filled with whatever this entry has: the
    /// now-playing indicator, else a media preview, else nothing.
    ///
    /// The preview used to be 44pt, which made every content-tab row taller
    /// than a song row and shifted the whole column. It is the same size as a
    /// song row's badge now, so the two lists line up.
    @ViewBuilder
    private var leadingIcon: some View {
        if isPlaying {
            if player.loading {
                ProgressView()
                    .controlSize(.mini)
                    .tint(Color.lsAccent)
            } else {
                Image(systemName: player.isPlaying ? "speaker.wave.2.fill" : "pause.fill")
                    .font(.caption)
                    .foregroundStyle(Color.lsAccent)
                    // Repeating symbol effects are content animations the
                    // system does not auto-suppress under Reduce Motion.
                    .symbolEffect(.variableColor.iterative, options: .repeating,
                                  isActive: player.isPlaying && !reduceMotion)
            }
        } else if let previewURL {
            thumbnail(url: previewURL)
        } else {
            Color.clear
        }
    }

    /// Through the proxy like every other CachedImage call site: the raw
    /// third-party URL meant no backend downscale (a 1280px YouTube thumbnail
    /// decoded for a tiny cell), no 429/Retry-After handling, and exposure to
    /// hotlink blocking.
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
