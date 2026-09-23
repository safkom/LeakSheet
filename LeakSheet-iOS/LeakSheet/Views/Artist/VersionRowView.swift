import SwiftUI

/// A specific version row — shown when a multi-version song is expanded.
struct VersionRowView: View {
    let version: SongVersion
    /// Position within the song's version list — fallback label when the
    /// version has no explicit tag, so untagged versions stay tellable apart.
    var versionIndex: Int? = nil
    /// The song this version belongs to — carries `songKey` for the
    /// description sheet's cross-era picker and enables Favourite in the menu.
    let song: Song
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let eraName: String
    let eraArt: String?
    var onPlay: ((SongVersion) -> Void)? = nil
    var onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player

    private var isPlaying: Bool {
        player.isNowPlaying(version, inEra: eraName)
    }

    private var canStream: Bool {
        version.isStreamable
    }

    private var versionLabel: String? {
        if let tag = version.versionTag { return tag }
        if let idx = versionIndex { return "#\(idx + 1)" }
        return nil
    }

    /// Length and leak date — what tells two takes apart before opening one.
    private var detail: String? {
        let parts = [version.trackLength, version.leakDate]
            .compactMap { $0?.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && $0 != "?:??" }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private var payload: DescriptionSheet.Payload {
        DescriptionSheet.Payload(
            song: song, version: version,
            artistName: artistName, artistSlug: artistSlug, eraName: eraName, eraArt: eraArt
        )
    }

    var body: some View {
        HStack(spacing: 8) {
            SongPlayControl(
                isCurrent: isPlaying,
                isLoading: player.loading,
                isPlaying: player.isPlaying,
                canStream: canStream,
                title: version.name,
                play: play
            )

            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    if let label = versionLabel {
                        Text(label)
                            .font(.caption.weight(.bold).monospacedDigit())
                            .foregroundStyle(isPlaying ? Color.lsAccent : .secondary)
                    }
                    if let b = version.badge, let badge = Badge(rawValue: b) {
                        Text(badge.emoji)
                            .font(.caption)
                    }
                }
                BadgeRowView(version: version, trailing: detail)
                CreditLineView(version: version)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            ThreeDotMenu(
                version: version, song: song,
                artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                eraName: eraName, eraArt: eraArt,
                onPlay: onPlay, onShowDescription: onShowDescription
            )
        }
        .padding(.vertical, 3)
        .padding(.leading, 24)
        .padding(.trailing, 2)
        .background(isPlaying ? Color.lsAccent.opacity(0.06) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .rowHoverHighlight()
        .contentShape(Rectangle())
        // Tap opens Details, never plays — matches every other row kind.
        .onTapGesture { onShowDescription(payload) }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
        .accessibilityValue(isPlaying ? "Now playing" : "")
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Shows details")
        .accessibilityActions {
            if canStream {
                Button("Play", action: play)
                Button("Add to Queue", action: queue)
            }
        }
        .swipeActions(edge: .trailing) {
            if canStream {
                Button(action: queue) {
                    Image(systemName: "text.append")
                }
                .tint(.lsAccent)
                .accessibilityLabel("Add \(version.name) to queue")
            }
        }
        .swipeActions(edge: .leading) {
            if canStream {
                Button(action: play) {
                    Image(systemName: "play.fill")
                }
                .tint(.green)
                .accessibilityLabel("Play \(version.name)")
            }
        }
        .contextMenu {
            SongContextMenu(
                version: version, song: song,
                artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                eraName: eraName, eraArt: eraArt,
                onPlay: onPlay, onShowDescription: onShowDescription
            )
        }
    }

    private var accessibilitySummary: String {
        var parts = ["Version \(versionLabel ?? "")"]
        if let b = version.badge, let badge = Badge(rawValue: b) { parts.append(badge.label) }
        if let quality = version.quality, !quality.isEmpty { parts.append(quality) }
        if let availability = version.availableLength, !availability.isEmpty { parts.append(availability) }
        if let detail { parts.append(detail) }
        return parts.joined(separator: ", ")
    }

    private func play() {
        guard canStream else { return }
        Haptics.light()
        if let onPlay {
            onPlay(version)
        } else {
            player.playTrack(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "", artistSlug: artistSlug)
        }
    }

    private func queue() {
        guard canStream else { return }
        player.addToQueue(version, artistName: artistName, eraName: eraName, artUrl: eraArt ?? "", artistSlug: artistSlug)
        Haptics.light()
    }
}
