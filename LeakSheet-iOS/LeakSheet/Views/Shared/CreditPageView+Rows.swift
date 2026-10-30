import SwiftUI

extension CreditPageView {
    // MARK: - Rows and chrome

    /// Title, tag and badge on one line over the quality pills, with the play control
    /// centred beside both: the era list's nested version row assumes a song header above it.
    func trackRow(_ c: CreditProfile.Credited, _ profile: CreditProfile) -> some View {
        let isCurrent = player.isNowPlaying(c.version, inEra: c.eraName)
        let heard = ListeningHistory.shared.isHeard(c.version, artistSlug: vm.artist.slug, eraName: c.eraName)
        let detail = [c.version.trackLength, c.version.leakDate]
            .compactMap { $0?.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && $0 != "?:??" }
            .joined(separator: " · ")
        return HStack(spacing: 10) {
            SongPlayControl(
                isCurrent: isCurrent, isLoading: player.loading, isPlaying: player.isPlaying,
                canStream: c.version.isStreamable, title: c.version.name, link: c.version.streamableLink,
                play: { play(c.version, in: profile.streamable) }
            )
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(c.song.baseName)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(isCurrent ? Color.lsAccent : .primary)
                        .lineLimit(1)
                    if heard {
                        HeardDot()
                    }
                    if let tag = c.version.versionTag {
                        Text(tag)
                            .font(.caption.weight(.bold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    if let badge = c.version.badge.flatMap(Badge.init(rawValue:)) {
                        Text(badge.emoji).font(.caption)
                    }
                }
                BadgeRowView(version: c.version, trailing: detail.isEmpty ? nil : detail)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            ThreeDotMenu(
                version: c.version, song: c.song,
                artistName: vm.artist.name, artistSlug: vm.artist.slug, sourceUrl: vm.artist.sourceUrl,
                eraName: c.eraName, eraArt: c.eraArt,
                onPlay: { play($0, in: profile.streamable) }, onShowDescription: { description = $0 }
            )
        }
        .padding(.vertical, 8)
        .contentShape(Rectangle())
        .onTapGesture { description = payload(c) }
        .accessibilityElement(children: .combine)
        .accessibilityValue(heard ? "played" : "")
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Shows details")
    }

    func payload(_ c: CreditProfile.Credited) -> DescriptionSheet.Payload {
        DescriptionSheet.Payload(
            song: c.song, version: c.version, artistName: vm.artist.name, artistSlug: vm.artist.slug,
            eraName: c.eraName, eraArt: c.eraArt
        )
    }

    static func count(_ n: Int, _ noun: String) -> String {
        "\(n.formatted()) \(n == 1 ? noun : noun + "s")"
    }

    func countRow(_ label: String, _ value: String, dot: Color? = nil) -> some View {
        HStack(spacing: 8) {
            if let dot {
                Circle().fill(dot).frame(width: 8, height: 8).accessibilityHidden(true)
            }
            Text(label).font(.subheadline)
            Spacer(minLength: 8)
            Text(value).font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    func playBar(_ profile: CreditProfile) -> some View {
        let list = profile.streamable
        if !list.isEmpty {
            HStack(spacing: 12) {
                Button {
                    Haptics.light()
                    player.playInList(items(list), startAt: 0)
                } label: {
                    Label("Play All", systemImage: "play.fill")
                        .font(.headline)
                        .foregroundStyle(Color.preferredText(on: .lsAccent, in: colorScheme))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(Color.lsAccent)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                Button {
                    Haptics.light()
                    player.playInList(items(list.shuffled()), startAt: 0)
                } label: {
                    Image(systemName: "shuffle")
                        .font(.headline)
                        .frame(width: 52, height: 52)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Shuffle all tracks")
                Button {
                    Haptics.light()
                    player.playCreditRadio(list, artistName: vm.artist.name, artistSlug: vm.artist.slug)
                } label: {
                    Image(systemName: "dot.radiowaves.left.and.right")
                        .font(.headline)
                        .frame(width: 52, height: 52)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Radio")
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
    }

    // MARK: - Playback

    private func items(_ list: [CreditProfile.Credited]) -> [PlaybackListItem] {
        list.map {
            PlaybackListItem(
                version: $0.version, artistName: vm.artist.name, eraName: $0.eraName,
                artUrl: $0.eraArt ?? "", artistSlug: vm.artist.slug
            )
        }
    }

    /// Starts the streamable list at the tapped version, so auto-advance continues down it.
    func play(_ version: SongVersion, in list: [CreditProfile.Credited]) {
        guard let idx = list.firstIndex(where: { $0.version == version }) else { return }
        Haptics.light()
        player.playInList(items(list), startAt: idx)
    }
}
