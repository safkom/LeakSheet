import SwiftUI

/// Convenience alias used throughout the app.
typealias DescriptionSheet = SongDescriptionSheet

/// Sheet showing detailed song/version information.
struct SongDescriptionSheet: View {
    let payload: Payload

    /// Set when hosted as the macOS Details inspector rather than presented as a
    /// sheet: the host supplies the chrome, and there is nothing to dismiss.
    let embedded: Bool

    /// Defined in Shared/Models so FavouritesManager and the tvOS detail screen
    /// can build one without depending on this sheet.
    typealias Payload = SongDetailPayload

    /// The version the sheet shows: `payload.version` until a picker chip is chosen.
    /// Everything below reads `active`, never `payload`, so the whole sheet follows it.
    struct ActiveVersion {
        var version: SongVersion
        var song: Song?
        var eraName: String
        var eraArt: String?
    }

    @State var active: ActiveVersion

    init(payload: Payload, embedded: Bool = false) {
        self.payload = payload
        self.embedded = embedded
        _active = State(initialValue: ActiveVersion(
            version: payload.version, song: payload.song,
            eraName: payload.eraName, eraArt: payload.eraArt
        ))
    }

    @Environment(\.dismiss) var dismiss
    @Environment(PlayerViewModel.self) var player
    @Environment(FavouritesManager.self) var favourites
    /// Contrast is judged against the Mac inspector's real system appearance: see
    /// DECISIONS.md::DesignTokens.swift::scheme-parameter.
    @Environment(\.colorScheme) var colorScheme

    @State var accentColor: Color?
    /// In-app Safari for version links + evidence — the sheet must never
    /// bounce the user out to system Safari.
    @State var safariItem: SafariItem?
    /// The credit page the embedded (Mac inspector) form presents; it has no stack to push onto.
    @State var creditSheet: CreditRef?
    /// Present when the sheet is shown from the artist screen — powers the
    /// cross-era version picker. Nil from Now Playing / Favourites, where the
    /// picker falls back to just this song's own versions.
    @Environment(ArtistViewModel.self) var environmentVM: ArtistViewModel?

    /// The environment's view model only when it describes this payload's artist
    /// (the Favourites sheet gets the *playing* artist's).
    var artistVM: ArtistViewModel? {
        guard let vm = environmentVM, let slug = payload.artistSlug, vm.artist.slug == slug else { return nil }
        return vm
    }

    /// One version, wherever it lives — its own era if the song is era-unique,
    /// or every era sharing the same `songKey` when it isn't. Falls back to the
    /// current era's own versions when there's no `ArtistViewModel` to ask
    /// (Now Playing / Favourites) or the song has no cross-era duplicates.
    var pickerVersions: [ArtistViewModel.CrossEraVersion] {
        if let vm = artistVM {
            let refs = vm.crossEraRefs(for: payload)
            if !refs.isEmpty {
                return refs.flatMap { ref in
                    ref.song.allVersions.map {
                        .init(version: $0, song: ref.song, eraName: ref.eraName, eraArt: ref.eraArt)
                    }
                }
            }
            // Era-unique song: songKeyEras drops single-era keys, so recover
            // the unfiltered song by base name rather than trusting the
            // payload's copy, which a badge filter may have truncated.
            if let resolved = vm.resolvedSong(for: payload) {
                return resolved.allVersions.map {
                    .init(version: $0, song: resolved, eraName: payload.eraName, eraArt: payload.eraArt)
                }
            }
        }
        let versions = payload.song?.allVersions ?? [payload.version]
        return versions.map {
            .init(version: $0, song: payload.song, eraName: payload.eraName, eraArt: payload.eraArt)
        }
    }

    /// Versions of songs linked to this one by name — its alt titles, the parts
    /// of a slash title, or another song naming this one (see
    /// ArtistViewModel.linkedRefs). Shown as their own row, apart from this
    /// song's versions, because a link is not a claim that they are one song.
    var linkedVersions: [ArtistViewModel.CrossEraVersion] {
        guard let vm = artistVM else { return [] }
        return vm.linkedRefs(for: payload).flatMap { ref in
            ref.song.allVersions.map {
                .init(version: $0, song: ref.song, eraName: ref.eraName, eraArt: ref.eraArt)
            }
        }
    }

    var badgeInfo: (emoji: String, label: String)? {
        guard let b = active.version.badge, let badge = Badge(rawValue: b) else { return nil }
        return (badge.emoji, badge.label)
    }

    var displayName: String {
        let n = active.version.name
        // Strip version tag suffix like " [V1]" for cleaner display
        if let tag = active.version.versionTag, n.hasSuffix(" [\(tag)]") {
            return String(n.dropLast(tag.count + 3))
        }
        return n
    }

    var subtitle: String? {
        active.version.altTitles?.first
    }

    var canStream: Bool {
        active.version.isStreamable
    }

    /// The active version's id without a chosen source, as song lists and picker chips carry it.
    var activeBaseID: String {
        active.version.playing(nil).id
    }

    /// Play the sheet's version. When the full song is known, hand the player
    /// the song's streamable versions as a list so playback continues instead
    /// of stopping after this one track.
    func play() {
        Haptics.light()
        if let song = active.song {
            // allVersions: a filtered copy would queue only the versions that
            // matched the badge filter, so playback stopped after one track.
            let streamable = song.allVersions.filter(\.isStreamable)
            if let idx = streamable.firstIndex(where: { $0.id == activeBaseID }) {
                let items = streamable.enumerated().map { i, version in
                    PlaybackListItem(
                        // The sheet's version keeps its chosen source.
                        version: i == idx ? active.version : version,
                        artistName: payload.artistName,
                        eraName: active.eraName,
                        artUrl: active.eraArt ?? "",
                        artistSlug: payload.artistSlug
                    )
                }
                player.playInList(items, startAt: idx)
                return
            }
        }
        player.playTrack(
            active.version,
            artistName: payload.artistName,
            eraName: active.eraName,
            artUrl: active.eraArt ?? "",
            artistSlug: payload.artistSlug ?? ""
        )
    }

    var body: some View {
        if embedded {
            content
                .webSheet(item: $safariItem)
                .sheet(item: $creditSheet) { CreditPageSheet(ref: $0) }
        } else {
            NavigationStack {
                content
                    .navigationTitle("Description")
                    #if os(iOS)
                    .toolbarTitleDisplayMode(.inline)
                    #endif
                    .toolbar { chromeToolbar }
                    .navigationDestination(for: CreditRef.self) { CreditPageView(ref: $0) }
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
            .webSheet(item: $safariItem)
        }
    }

    var content: some View {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        artHeader
                        titleBlock
                        creditsSection
                        statusBadges
                        // Version picker — every version of this song, across
                        // every era it appears in (fallback: just this era's
                        // versions when the song has no cross-era duplicates).
                        versionPicker
                        // Detail grid (2-column)
                        detailGrid
                        streamInfo
                        storySections
                        linkSections
                    }
                    .padding(20)
                }
                bottomBar
            }
            .background(
                ZStack {
                    Color.lsBackground
                    if let accent = accentColor {
                        LinearGradient(
                            colors: [accent.opacity(0.15), Color.clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    }
                }
                .ignoresSafeArea()
            )
    }

}
