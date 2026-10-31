#if os(macOS)
import SwiftUI

extension MacArtistView {
    // MARK: - Content

    @ViewBuilder
    func content(_ rows: [MacListRow]) -> some View {
        if vm.isFiltering && rows.isEmpty && !isMiscMode {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if isMiscMode {
            miscContent
        } else if openEra == nil && !isFlatMode {
            eraGridContent
        } else if rows.isEmpty {
            VStack(spacing: 0) {
                pageHeader
                    .frame(maxWidth: Metrics.contentMaxWidth)
                emptyState
            }
        } else {
            songList(rows)
        }
    }

    private var miscContent: some View {
        ScrollView {
            VStack(spacing: 0) {
                pageHeader
                MiscListView(
                    vm: vm,
                    artistName: artist.name,
                    artistSlug: artist.slug,
                    eraArtByLowercasedName: eraArtByLowercasedName,
                    onShowDescription: showDetails,
                    onOpenLink: openLink
                )
                .id(vm.selectedTabKey ?? "misc")
                .padding(.bottom, 12)
            }
            .frame(maxWidth: Metrics.contentMaxWidth)
            .frame(maxWidth: .infinity)
        }
    }

    private var eraGridContent: some View {
        ScrollView {
            VStack(spacing: 0) {
                pageHeader
                MacEraGrid(
                    vm: vm,
                    onSelect: { eraName in
                        vm.openEra(eraName)
                        ui.selectedSong = nil
                    },
                    onInfo: showEraInfo
                )
            }
            .frame(maxWidth: Metrics.contentMaxWidth)
            .frame(maxWidth: .infinity)
        }
    }

    private func songList(_ rows: [MacListRow]) -> some View {
        MacSongList(
            rows: rows,
            artistName: artist.name,
            artistSlug: artist.slug,
            sourceUrl: artist.sourceUrl,
            onToggleExpansion: openEra == nil ? nil : { eraName, ordinal in
                vm.toggleSongExpansion(eraName: eraName, ordinal: ordinal)
            },
            onPlay: { version, eraName in play(version, eraName: eraName, in: rows) },
            onShowDescription: showDetails,
            onSelect: { row in
                ui.selectedSong = row?.payload(artistName: artist.name, artistSlug: artist.slug)
            },
            header: { pageHeader }
        )
        // Fresh selection per mode/era — the list is a different list.
        .id(openEra ?? "flat")
        .frame(maxWidth: Metrics.contentMaxWidth)
        .frame(maxWidth: .infinity)
    }

    @ViewBuilder
    private var emptyState: some View {
        if vm.isSearching {
            ContentUnavailableView.search(text: vm.content.state.query)
        } else if vm.recents {
            ContentUnavailableView(
                "No Recent Leaks", systemImage: "clock",
                description: Text("No versions carry a leak or file date.")
            )
        } else if isFlatMode {
            ContentUnavailableView(
                "No Matches", systemImage: "line.3.horizontal.decrease.circle",
                description: Text("Nothing matches the current filters.")
            )
        } else {
            ContentUnavailableView(
                "No Songs", systemImage: "music.note.list",
                description: Text("This era has no songs yet.")
            )
        }
    }

    // MARK: - Rows

    /// One flat row list for whatever mode is active. Each branch reuses the
    /// arrays the view model already computed off-main; nothing is filtered or
    /// sorted here.
    var visibleRows: [MacListRow] {
        if vm.isSearching {
            return vm.content.searchResults.map {
                .song(
                    $0.song,
                    version: $0.version,
                    eraName: $0.era.name,
                    eraArt: $0.era.artUrl,
                    ordinal: $0.songOrdinal
                )
            }
        }
        if vm.recents {
            return vm.visibleRecents.map {
                .song(
                    $0.song,
                    version: $0.version,
                    eraName: $0.era.name,
                    eraArt: $0.era.artUrl,
                    ordinal: $0.songOrdinal
                )
            }
        }
        if vm.isBadgeFilterActive {
            return flatEraRows
        }
        guard let openEra else { return [] }
        return rows(forEra: openEra)
    }

    /// Every era's songs in one list, with an era header between groups —
    /// the shape the badge filters and content tabs need.
    private var flatEraRows: [MacListRow] {
        var out: [MacListRow] = []
        for era in vm.content.eras {
            let songs = era.allSongs
            guard !songs.isEmpty else { continue }
            out.append(.header(era.era.name, id: era.era.name))
            for (ordinal, song) in songs.enumerated() {
                out.append(.song(
                    song, version: song.bestPlayableVersion ?? song.versions.first,
                    eraName: era.era.name, eraArt: era.era.artUrl, ordinal: ordinal
                ))
            }
        }
        return out
    }

    /// One era's rows, taken straight from the view model's prepared
    /// `eraRows` — `rebuildEraRows` emits song/version rows only for the single
    /// expanded era, so filtering by name yields exactly this era's content.
    private func rows(forEra name: String) -> [MacListRow] {
        vm.eraRows.compactMap { row -> MacListRow? in
            guard row.eraName == name else { return nil }
            switch row {
            case .card, .divider, .eraGap:
                return nil
            case .groupHeader(let text, _, _):
                return .header(text, id: row.id)
            case .sectionHeader(let sectionName, _, _, _, _):
                return .header(sectionName, id: row.id)
            case .song(let song, let eraName, let eraArt, _, _, _, let ordinal):
                return .song(
                    song, version: song.bestPlayableVersion ?? song.versions.first,
                    eraName: eraName, eraArt: eraArt, ordinal: ordinal
                )
            case .version(let version, let index, let song, let eraName, let eraArt, _, let songOrdinal):
                return .version(
                    version, song: song, eraName: eraName, eraArt: eraArt,
                    index: index, ordinal: songOrdinal
                )
            }
        }
    }

    // MARK: - Actions

    func showEraInfo(_ name: String) {
        ui.selectedEra = name
        ui.inspectorTab = .era
        ui.showInspector = true
    }

    /// Details is a panel, never a modal — selecting a row already updates it,
    /// and an explicit Details action just makes sure the rail is showing.
    private func showDetails(_ payload: DescriptionSheet.Payload) {
        ui.selectedSong = payload
        ui.inspectorTab = .details
        ui.showInspector = true
    }

    /// Embeddable hosts get their in-app player; everything else opens in the
    /// user's browser (`webSheet` hands off to NSWorkspace on macOS).
    private func openLink(_ link: MiscLink) {
        guard let url = URL(string: link.url) else { return }
        if link.kind == .embed, let embedURL = MiscLinkClassifier.embedURL(for: link.url) {
            embedItem = EmbedItem(originalURL: url, embedURL: embedURL, title: link.label)
        } else {
            safariItem = SafariItem(url: url)
        }
    }

    // MARK: - Playback

    /// Play with the visible list as the auto-advance context, so playback
    /// continues down whatever the user is actually looking at.
    func play(_ version: SongVersion, eraName: String, in rows: [MacListRow]) {
        if let openEra, !isFlatMode, openEra == eraName,
           let filtered = vm.filteredEra(named: eraName) {
            player.playInEra(
                version, eraName: eraName, artistName: artist.name,
                artUrl: filtered.era.artUrl ?? "",
                versions: filtered.streamableVersions, artistSlug: artist.slug
            )
            return
        }
        let items: [PlaybackListItem] = rows.compactMap { row in
            switch row {
            case .header: return nil
            case .song(let song, let v, let era, let art, _):
                guard let picked = v ?? song.bestPlayableVersion, picked.isStreamable else { return nil }
                return PlaybackListItem(
                    version: picked,
                    artistName: artist.name,
                    eraName: era,
                    artUrl: art ?? "",
                    artistSlug: artist.slug
                )
            case .version(let v, _, let era, let art, _, _):
                guard v.isStreamable else { return nil }
                return PlaybackListItem(
                    version: v,
                    artistName: artist.name,
                    eraName: era,
                    artUrl: art ?? "",
                    artistSlug: artist.slug
                )
            }
        }
        if let idx = items.firstIndex(where: { $0.version.id == version.id }) {
            player.playInList(items, startAt: idx)
        } else {
            player.playTrack(version, artistName: artist.name, eraName: eraName, artUrl: "", artistSlug: artist.slug)
        }
    }
}
#endif
