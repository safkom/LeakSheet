import SwiftUI

/// A song row. Select plays the first streamable version outright — the common
/// case on a couch. Everything else (other versions, queue, favourite, links,
/// full metadata) lives on the detail screen reached from the row's second
/// button, because tvOS has neither swipe actions nor context menus.
struct TVSongRowView: View {
    let song: Song
    let eraName: String
    let eraArt: String?
    let artist: Artist

    @Environment(PlayerViewModel.self) private var player

    private var primary: SongVersion? {
        song.versions.first(where: \.isStreamable) ?? song.versions.first
    }

    private var isPlaying: Bool {
        guard let primary, let current = player.currentTrack else { return false }
        return current.id == primary.id
    }

    var body: some View {
        HStack(spacing: 12) {
            Button {
                play()
            } label: {
                HStack(spacing: 16) {
                    Image(systemName: isPlaying ? "speaker.wave.2.fill" : "play.circle")
                        .foregroundStyle(isPlaying ? Color.lsPrimary : .secondary)
                        .frame(width: 34)

                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 8) {
                            if let badge = song.badge {
                                Text(Badge(rawValue: badge)?.emoji ?? "")
                            }
                            Text(song.baseName)
                                .lineLimit(1)
                        }
                        if let primary {
                            BadgeRowView(version: primary)
                            CreditTagsView(version: primary)
                        }
                    }

                    Spacer()

                    if song.versions.count > 1 {
                        Text("\(song.versions.count)v")
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 12)
                .contentShape(Rectangle())
            }
            .buttonStyle(TVRowButtonStyle())
            .disabled(primary == nil)

            if let payload = detailPayload {
                NavigationLink(value: TVRoute.song(payload)) {
                    Image(systemName: "info.circle")
                        .padding(18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(TVRowButtonStyle())
                .accessibilityLabel("Details for \(song.baseName)")
            }
        }
        .padding(.horizontal, 36)
    }

    private var detailPayload: SongDetailPayload? {
        guard let version = song.versions.first else { return nil }
        return SongDetailPayload(
            song: song,
            version: version,
            artistName: artist.name,
            artistSlug: artist.slug,
            eraName: eraName,
            eraArt: eraArt
        )
    }

    private func play() {
        guard let primary else { return }
        player.playInEra(
            primary,
            eraName: eraName,
            artistName: artist.name,
            artUrl: eraArt ?? "",
            versions: song.versions.filter(\.isStreamable),
            artistSlug: artist.slug
        )
    }
}

/// A single version row — used by search results, where the match is a specific
/// version rather than a whole song.
struct TVVersionRowView: View {
    let version: SongVersion
    let song: Song
    let eraName: String
    let eraArt: String?
    let artist: Artist

    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        HStack(spacing: 12) {
            Button {
                player.playInEra(
                    version,
                    eraName: eraName,
                    artistName: artist.name,
                    artUrl: eraArt ?? "",
                    versions: [version],
                    artistSlug: artist.slug
                )
            } label: {
                HStack(spacing: 16) {
                    Image(systemName: "play.circle")
                        .foregroundStyle(.secondary)
                        .frame(width: 34)
                    VStack(alignment: .leading, spacing: 6) {
                        Text(version.name)
                            .lineLimit(1)
                        Text(eraName)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        BadgeRowView(version: version)
                    }
                    Spacer()
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 12)
                .contentShape(Rectangle())
            }
            .buttonStyle(TVRowButtonStyle())
            .disabled(!version.isStreamable)

            NavigationLink(value: TVRoute.song(SongDetailPayload(
                song: song,
                version: version,
                artistName: artist.name,
                artistSlug: artist.slug,
                eraName: eraName,
                eraArt: eraArt
            ))) {
                Image(systemName: "info.circle")
                    .padding(18)
                    .contentShape(Rectangle())
            }
            .buttonStyle(TVRowButtonStyle())
            .accessibilityLabel("Details for \(version.name)")
        }
        .padding(.horizontal, 36)
    }
}

/// Misc / music-video entries. Anything not natively streamable becomes a QR
/// code rather than a dead row — tvOS has no browser to hand off to.
struct TVMiscRowView: View {
    let entry: MiscEntry

    @State private var qrItem: QRItem?

    var body: some View {
        Button {
            qrItem = entry.links.first
                .flatMap(URL.init(string:))
                .map { QRItem(url: $0, title: entry.name) }
        } label: {
            HStack(spacing: 16) {
                Image(systemName: "link")
                    .foregroundStyle(.secondary)
                    .frame(width: 34)
                VStack(alignment: .leading, spacing: 6) {
                    Text(entry.name)
                        .lineLimit(1)
                    if let notes = entry.notes, !notes.isEmpty {
                        Text(notes)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                Spacer()
                if !entry.links.isEmpty {
                    Image(systemName: "qrcode")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(TVRowButtonStyle())
        .disabled(entry.links.isEmpty)
        .padding(.horizontal, 36)
        .sheet(item: $qrItem) { QRCodeSheet(item: $0) }
    }
}
