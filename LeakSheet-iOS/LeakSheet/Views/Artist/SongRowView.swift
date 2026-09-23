import SwiftUI

/// A single song row: play control, title, badges, credits, and actions.
struct SongRowView: View {
    let song: Song
    let version: SongVersion?
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let eraName: String
    let eraArt: String?
    var showVersionBadge: Bool = false
    /// Whether this multi-version row's versions are showing below it.
    var isExpanded: Bool = false
    var onPlay: ((SongVersion) -> Void)? = nil
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    private var isPlaying: Bool {
        player.isNowPlaying(version, inEra: eraName)
    }

    private var canStream: Bool {
        version?.isStreamable ?? false
    }

    /// Collapsed multi-version row: summarises the song rather than one take.
    private var isSummary: Bool {
        song.hasMultipleVersions && !showVersionBadge
    }

    /// Recents/search show the version's own badge; the tree shows the song's.
    private var badge: Badge? {
        if showVersionBadge {
            return version?.badge.flatMap(Badge.init(rawValue:))
        }
        return song.computedBadge
    }

    private var isFavourite: Bool {
        favourites.isFavourited(song: song, artistSlug: artistSlug, eraName: eraName)
    }

    /// The first alternate title that differs from the base name. The row's
    /// own version leads, so a collapsed row never advertises another take's alias.
    private var akaTitle: String? {
        let ordered = version.map { [$0] + song.versions } ?? song.versions
        for v in ordered {
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
            SongPlayControl(
                isCurrent: isPlaying,
                isLoading: player.loading,
                isPlaying: player.isPlaying,
                canStream: canStream,
                title: song.baseName,
                play: play
            )

            VStack(alignment: .leading, spacing: 3) {
                SongTitleLine(
                    title: song.baseName,
                    badge: badge,
                    versionTag: showVersionBadge ? version?.versionTag : nil,
                    isPlaying: isPlaying
                )
                if let aka = akaTitle {
                    Text(aka)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                // bestPlayableVersion on a summary row: the badges must describe
                // the version its play button plays.
                if let shown = isSummary ? song.bestPlayableVersion : version {
                    BadgeRowView(version: shown, trailing: isSummary ? "\(song.versions.count) versions" : nil)
                } else if isSummary {
                    Text("\(song.versions.count) versions")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                if !isSummary, let version {
                    CreditLineView(version: version)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if isSummary {
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .rotationEffect(.degrees(isExpanded ? 90 : 0))
                    .animation(.snappy, value: isExpanded)
            }
            if let version {
                ThreeDotMenu(
                    version: version, song: song,
                    artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                    eraName: eraName, eraArt: eraArt,
                    onPlay: onPlay, onShowDescription: onShowDescription
                )
            }
        }
        .padding(.vertical, 6)
        .padding(.leading, 4)
        .padding(.trailing, 2)
        .background(isPlaying ? Color.lsAccent.opacity(0.08) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .rowHoverHighlight()
        // One VoiceOver stop per song, with its actions named.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
        .accessibilityValue(isPlaying ? "Now playing" : "")
        .accessibilityHint(isSummary ? (isExpanded ? "Hides versions" : "Shows versions") : "Shows details")
        .accessibilityActions {
            if canStream {
                Button("Play", action: play)
                Button("Add to Queue", action: queue)
            }
            Button(isFavourite ? "Remove from Favourites" : "Add to Favourites", action: toggleFavourite)
            if let version {
                Button("Details") { onShowDescription(payload(for: version)) }
            }
        }
        .swipeActions(edge: .trailing) {
            Button(action: toggleFavourite) {
                Image(systemName: isFavourite ? "heart.fill" : "heart")
            }
            .tint(.pink)
            .accessibilityLabel(isFavourite ? "Remove \(song.baseName) from favourites" : "Add \(song.baseName) to favourites")

            if canStream {
                Button(action: queue) {
                    Image(systemName: "text.append")
                }
                .tint(.lsAccent)
                .accessibilityLabel("Add \(song.baseName) to queue")
            }
        }
        .swipeActions(edge: .leading) {
            if canStream {
                Button(action: play) {
                    Image(systemName: "play.fill")
                }
                .tint(.green)
                .accessibilityLabel("Play \(song.baseName)")
            }
        }
        .contextMenu {
            if let version {
                SongContextMenu(
                    version: version, song: song,
                    artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                    eraName: eraName, eraArt: eraArt,
                    onPlay: onPlay, onShowDescription: onShowDescription
                )
            }
        }
    }

    private var accessibilitySummary: String {
        var parts: [String] = []
        if let badge { parts.append(badge.label) }
        parts.append(song.baseName)
        if let tag = showVersionBadge ? version?.versionTag : nil { parts.append(tag) }
        if let aka = akaTitle { parts.append("also known as \(aka)") }
        let shown = isSummary ? song.bestPlayableVersion : version
        if let quality = shown?.quality, !quality.isEmpty { parts.append(quality) }
        if let availability = shown?.availableLength, !availability.isEmpty { parts.append(availability) }
        if isSummary { parts.append("\(song.versions.count) versions") }
        return parts.joined(separator: ", ")
    }

    private func payload(for version: SongVersion) -> DescriptionSheet.Payload {
        DescriptionSheet.Payload(
            song: song, version: version,
            artistName: artistName, artistSlug: artistSlug, eraName: eraName, eraArt: eraArt
        )
    }

    private func play() {
        guard canStream, let version else { return }
        Haptics.light()
        if let onPlay {
            onPlay(version)
        } else {
            player.playTrack(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "", artistSlug: artistSlug)
        }
    }

    private func queue() {
        guard canStream, let version else { return }
        player.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "", artistSlug: artistSlug)
        Haptics.light()
    }

    private func toggleFavourite() {
        guard version != nil else { return }
        favourites.toggle(
            song: song, artistSlug: artistSlug, artistName: artistName,
            sourceUrl: sourceUrl, eraName: eraName, eraArt: eraArt
        )
        Haptics.light()
    }
}

/// The row's leading control: what is playing, or a play button for anything
/// streamable, so the row itself says a song can be played.
struct SongPlayControl: View {
    let isCurrent: Bool
    let isLoading: Bool
    let isPlaying: Bool
    let canStream: Bool
    let title: String
    let play: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Group {
            if isCurrent && isLoading {
                ProgressView()
                    .controlSize(.mini)
                    .tint(Color.lsAccent)
            } else if isCurrent {
                Image(systemName: isPlaying ? "speaker.wave.2.fill" : "pause.fill")
                    .font(.footnote)
                    .foregroundStyle(Color.lsAccent)
                    // Repeating symbol effects are not suppressed by Reduce Motion.
                    .symbolEffect(.variableColor.iterative, options: .repeating, isActive: isPlaying && !reduceMotion)
            } else if canStream {
                Button(action: play) {
                    Image(systemName: "play.fill")
                        .font(.caption)
                        .foregroundStyle(Color.lsAccent)
                        .frame(width: 28, height: 28)
                        .background(Circle().fill(Color.lsAccent.opacity(0.14)))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Play \(title)")
            } else {
                Color.clear
            }
        }
        .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
        .contentShape(Rectangle())
    }
}

/// Badge, title and (in flat lists) the version tag, on one line.
private struct SongTitleLine: View {
    let title: String
    let badge: Badge?
    let versionTag: String?
    let isPlaying: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 5) {
            if let badge {
                Text(badge.emoji)
                    .font(.caption)
            }
            Text(title)
                .font(.subheadline)
                .foregroundStyle(isPlaying ? Color.lsAccent : .primary)
                .fixedSize(horizontal: false, vertical: true)
            if let versionTag {
                Text("[\(versionTag)]")
                    .font(.caption.weight(.bold).monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
    }
}
