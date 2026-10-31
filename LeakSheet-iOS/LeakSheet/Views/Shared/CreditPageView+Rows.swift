import SwiftUI

extension CreditPageView {
    // MARK: - Rows and chrome

    /// Title, tag and badge on one line over the quality pills, with the play control
    /// centred beside both: the era list's nested version row assumes a song header above it.
    func trackRow(_ credited: CreditProfile.Credited, _ profile: CreditProfile) -> some View {
        let isCurrent = player.isNowPlaying(credited.version, inEra: credited.eraName)
        let heard = ListeningHistory.shared.isHeard(
            credited.version,
            artistSlug: viewModel.artist.slug,
            eraName: credited.eraName
        )
        let detail = [credited.version.trackLength, credited.version.leakDate]
            .compactMap { $0?.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && $0 != "?:??" }
            .joined(separator: " · ")
        return HStack(spacing: 10) {
            SongPlayControl(
                isCurrent: isCurrent, isLoading: player.loading, isPlaying: player.isPlaying,
                canStream: credited.version.isStreamable, title: credited.version.name,
                link: credited.version.streamableLink,
                play: { play(credited.version, in: profile.streamable) }
            )
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(credited.song.baseName)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(isCurrent ? Color.lsAccent : .primary)
                        .lineLimit(1)
                    if heard {
                        HeardDot()
                    }
                    if let tag = credited.version.versionTag {
                        Text(tag)
                            .font(.caption.weight(.bold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    if let badge = credited.version.badge.flatMap(Badge.init(rawValue:)) {
                        Text(badge.emoji).font(.caption)
                    }
                }
                BadgeRowView(version: credited.version, trailing: detail.isEmpty ? nil : detail)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            ThreeDotMenu(
                version: credited.version, song: credited.song,
                artistName: viewModel.artist.name, artistSlug: viewModel.artist.slug,
                sourceUrl: viewModel.artist.sourceUrl,
                eraName: credited.eraName, eraArt: credited.eraArt,
                onPlay: { play($0, in: profile.streamable) }, onShowDescription: { description = $0 }
            )
        }
        .padding(.vertical, 8)
        .contentShape(Rectangle())
        .onTapGesture { description = payload(credited) }
        .accessibilityElement(children: .combine)
        .accessibilityValue(heard ? "played" : "")
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Shows details")
    }

    func payload(_ credited: CreditProfile.Credited) -> DescriptionSheet.Payload {
        DescriptionSheet.Payload(
            song: credited.song, version: credited.version,
            artistName: viewModel.artist.name, artistSlug: viewModel.artist.slug,
            eraName: credited.eraName, eraArt: credited.eraArt
        )
    }

    static func count(_ amount: Int, _ noun: String) -> String {
        "\(amount.formatted()) \(amount == 1 ? noun : noun + "s")"
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
                    player.playCreditRadio(list, artistName: viewModel.artist.name, artistSlug: viewModel.artist.slug)
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
                version: $0.version, artistName: viewModel.artist.name, eraName: $0.eraName,
                artUrl: $0.eraArt ?? "", artistSlug: viewModel.artist.slug
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
