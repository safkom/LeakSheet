#if os(macOS)
import SwiftUI

/// The Mac artist screen: a header (art, name, stats, filters), then either the
/// era grid or one era's song list.
///
/// Forked from `ArtistView` rather than shared. The iOS screen is one flattened
/// `LazyVStack` of accordion rows driven by taps and swipes; this one is a grid
/// plus a selectable `List` driven by clicks, keys and hover. They agree on the
/// view model — every filter, search and playback path below calls the same
/// `ArtistViewModel` the iOS screen does.
struct MacArtistView: View {
    let artist: Artist
    @Bindable var vm: ArtistViewModel

    @State private var ui = MacUIState.shared
    @State private var listSelection: MacSongList.Row.ID?
    @State private var lastUpdated: Date?
    @State private var showStats = false
    @State private var showTimeline = false
    @State private var showLegend = false
    @State private var safariItem: SafariItem?
    @State private var embedItem: EmbedItem?

    @Environment(PlayerViewModel.self) private var player

    /// era name (lowercased) → art URL, first occurrence wins. Precomputed once
    /// so `MiscListView` takes a small dictionary instead of the whole era tree.
    private let eraArtByLowercasedName: [String: String?]

    init(artist: Artist, vm: ArtistViewModel) {
        self.artist = artist
        self.vm = vm
        var eraArt: [String: String?] = [:]
        for era in artist.eras where eraArt[era.name.lowercased()] == nil {
            eraArt[era.name.lowercased()] = era.artUrl
        }
        self.eraArtByLowercasedName = eraArt
    }

    /// The era drilled into, or nil for the grid. Search, the badge filters and
    /// the content tabs all produce a flat cross-era list, so they force the
    /// list view regardless.
    private var openEra: String? {
        isFlatMode ? nil : ui.openEra[artist.slug]
    }

    /// True when the filter state produces one cross-era song list rather than a
    /// per-era browse. `isEraExpanded` already returns true for every era under a
    /// badge filter, so the grid would be a dead end there.
    private var isFlatMode: Bool {
        vm.isSearching || vm.isBadgeFilterActive || vm.recents || isMiscMode
    }

    /// Content tabs (Misc / Music Videos / Released / Stems) carry `MiscEntry`
    /// values, not songs, so they render through the shared accordion rather
    /// than the selectable song list.
    ///
    /// ponytail: reuses the iOS `MiscListView` verbatim — no selection, no
    /// keyboard, no hover controls on these rows. Fork it too if content tabs
    /// become something people browse rather than dip into.
    private var isMiscMode: Bool {
        vm.misc || vm.selectedTabKey != nil
    }

    private var hasTimeline: Bool {
        artist.eras.contains { !($0.timeline ?? []).isEmpty }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Color.lsBorder)
            content
        }
        .frame(maxWidth: .infinity)
        .background(Color.lsBackground)
        .navigationTitle(openEra ?? artist.name)
        .navigationSubtitle(subtitleText)
        .searchable(text: $vm.searchQuery, prompt: "Search songs…")
        .toolbar { toolbarItems }
        .sheet(isPresented: $showStats) {
            if let trackerStats = artist.trackerStats { TrackerStatsSheet(stats: trackerStats) }
        }
        .sheet(isPresented: $showTimeline) { TrackerTimelineSheet(artist: artist) }
        .sheet(isPresented: $showLegend) { BadgeLegendSheet() }
        .webSheet(item: $safariItem)
        .sheet(item: $embedItem) { EmbedPlayerView(item: $0) }
        // The selection *is* the Details panel's input — no click opens a modal.
        .onChange(of: listSelection) { _, id in
            guard let id, let row = visibleRows.first(where: { $0.id == id }) else { return }
            ui.selectedSong = row.payload(artistName: artist.name, artistSlug: artist.slug)
        }
        .task(id: artist.slug) {
            listSelection = nil
            if let url = artist.sourceUrl {
                lastUpdated = await CacheService.shared.getCachedMeta(for: url)?.timestamp
            }
            player.setArtistEras(vm.eraPlaybackContexts)
            await vm.warmEraArt()
        }
    }

    private var subtitleText: String {
        if let openEra, let era = vm.filteredEra(named: openEra) {
            let n = era.allSongs.count
            return "\(n) song\(n == 1 ? "" : "s") · \(artist.name)"
        }
        return "\(vm.artistStats.total) tracks"
    }

    // MARK: - Header

    private var header: some View {
        VStack(spacing: 10) {
            if let notices = artist.notices, !notices.isEmpty {
                VStack(spacing: 4) {
                    ForEach(notices) { notice in
                        NoticeBannerView(notice: notice) { safariItem = SafariItem(url: $0) }
                    }
                }
            }

            ArtistStatsBarView(
                stats: vm.artistStats,
                onTap: artist.trackerStats != nil ? { showStats = true } : nil
            )

            // FlowLayout, not a horizontal scroller: a Mac has no scroll
            // affordance on an indicator-less strip, so chips past the fold
            // were simply invisible.
            FlowLayout(spacing: 8) {
                MacFilterChip(label: "Best Of", icon: "star.fill", isActive: vm.bestOf, tint: .filterBestOf) { vm.toggleBestOf() }
                MacFilterChip(label: "Worst Of", icon: "hand.thumbsdown", isActive: vm.worstOf, tint: .filterBestOf) { vm.toggleWorstOf() }
                MacFilterChip(label: "Grails", icon: "trophy.fill", isActive: vm.grails, tint: .filterGrail) { vm.toggleGrails() }
                MacFilterChip(label: "Recent", icon: "clock", isActive: vm.recents, tint: .filterRecent) { vm.toggleRecents() }
                MacFilterChip(label: "No Snippets", icon: "waveform.slash", isActive: vm.noSnippets, tint: .filterNoSnippets) { vm.toggleNoSnippets() }
                if !vm.availableTabs.isEmpty {
                    ForEach(vm.availableTabs) { tab in
                        MacFilterChip(
                            label: tab.name,
                            icon: FilterTogglesView.tabIcon(for: tab.kind),
                            isActive: vm.selectedTabKey == tab.id,
                            tint: .filterMisc
                        ) { vm.selectTab(tab.id) }
                    }
                } else if vm.hasMiscEntries {
                    MacFilterChip(label: "Misc", icon: "film.stack", isActive: vm.misc, tint: .filterMisc) { vm.toggleMisc() }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if let lastUpdated {
                Text("Updated \(lastUpdated.formatted(.relative(presentation: .named)))")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .frame(maxWidth: Metrics.contentMaxWidth)
    }

    @ToolbarContentBuilder
    private var toolbarItems: some ToolbarContent {
        ToolbarItemGroup {
            if openEra != nil {
                Button {
                    ui.openEra[artist.slug] = nil
                    vm.openEra(nil)
                    listSelection = nil
                } label: {
                    Label("All Eras", systemImage: "chevron.backward")
                }
                .help("Back to all eras")
            }

            Menu {
                if artist.trackerStats != nil {
                    Button { showStats = true } label: { Label("Stats", systemImage: "chart.bar.xaxis") }
                }
                if hasTimeline {
                    Button { showTimeline = true } label: { Label("Timeline", systemImage: "clock") }
                }
                Button { showLegend = true } label: { Label("Badge Legend", systemImage: "info.circle") }
            } label: {
                Label("More", systemImage: "ellipsis")
            }

            Button {
                ui.inspectorTab = .queue
                ui.showInspector = true
            } label: {
                Label("Queue", systemImage: "list.bullet")
            }
            .help("Show the queue")
        }
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if vm.isFiltering && visibleRows.isEmpty && !isMiscMode {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if isMiscMode {
            ScrollView {
                MiscListView(
                    vm: vm,
                    artistName: artist.name,
                    artistSlug: artist.slug,
                    eraArtByLowercasedName: eraArtByLowercasedName,
                    onShowDescription: showDetails,
                    onOpenLink: openLink
                )
                .id(vm.selectedTabKey ?? "misc")
                .padding(.vertical, 12)
                .frame(maxWidth: Metrics.contentMaxWidth)
                .frame(maxWidth: .infinity)
            }
        } else if openEra == nil && !isFlatMode {
            ScrollView {
                MacEraGrid(vm: vm) { eraName in
                    ui.openEra[artist.slug] = eraName
                    vm.openEra(eraName)
                    listSelection = nil
                }
                .padding(.top, 16)
                .frame(maxWidth: Metrics.contentMaxWidth)
                .frame(maxWidth: .infinity)
            }
        } else if visibleRows.isEmpty {
            emptyState
        } else {
            MacSongList(
                rows: visibleRows,
                artistName: artist.name,
                artistSlug: artist.slug,
                sourceUrl: artist.sourceUrl,
                onToggleExpansion: openEra == nil ? nil : { eraName, ordinal in
                    vm.toggleSongExpansion(eraName: eraName, ordinal: ordinal)
                },
                onPlay: play,
                onShowDescription: showDetails,
                selection: $listSelection
            )
            .frame(maxWidth: Metrics.contentMaxWidth)
            .frame(maxWidth: .infinity)
        }
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
    private var visibleRows: [MacSongList.Row] {
        if vm.isSearching {
            return vm.content.searchResults.map {
                .song($0.song, version: $0.version, eraName: $0.era.name, eraArt: $0.era.artUrl, ordinal: $0.songOrdinal)
            }
        }
        if vm.recents {
            return vm.visibleRecents.map {
                .song($0.song, version: $0.version, eraName: $0.era.name, eraArt: $0.era.artUrl, ordinal: $0.songOrdinal)
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
    private var flatEraRows: [MacSongList.Row] {
        var out: [MacSongList.Row] = []
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
    private func rows(forEra name: String) -> [MacSongList.Row] {
        vm.eraRows.compactMap { row -> MacSongList.Row? in
            guard row.eraName == name else { return nil }
            switch row {
            case .card, .divider, .eraGap:
                return nil
            case .groupHeader(let text, _):
                return .header(text, id: "g:\(text)")
            case .sectionHeader(let sectionName, _, _):
                return .header(sectionName, id: "s:\(sectionName)")
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
    private func play(_ version: SongVersion, eraName: String) {
        if let openEra, !isFlatMode, openEra == eraName,
           let filtered = vm.filteredEra(named: eraName) {
            player.playInEra(
                version, eraName: eraName, artistName: artist.name,
                artUrl: filtered.era.artUrl ?? "",
                versions: filtered.streamableVersions, artistSlug: artist.slug
            )
            return
        }
        let items: [PlaybackListItem] = visibleRows.compactMap { row in
            switch row {
            case .header: return nil
            case .song(let song, let v, let era, let art, _):
                guard let picked = v ?? song.bestPlayableVersion, picked.isStreamable else { return nil }
                return PlaybackListItem(version: picked, artistName: artist.name, eraName: era, artUrl: art ?? "", artistSlug: artist.slug)
            case .version(let v, _, let era, let art, _, _):
                guard v.isStreamable else { return nil }
                return PlaybackListItem(version: v, artistName: artist.name, eraName: era, artUrl: art ?? "", artistSlug: artist.slug)
            }
        }
        if let idx = items.firstIndex(where: { $0.version.id == version.id }) {
            player.playInList(items, startAt: idx)
        } else {
            player.playTrack(version, artistName: artist.name, eraName: eraName, artUrl: "", artistSlug: artist.slug)
        }
    }
}

/// Filter chip at Mac control height. The iOS chip carries a 44pt minimum and
/// full glass; here it reads as a toggle in a control strip.
private struct MacFilterChip: View {
    let label: String
    let icon: String
    let isActive: Bool
    var tint: Color = .lsAccent
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            Label(label, systemImage: icon)
                .font(.caption.weight(.medium))
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .frame(minHeight: Metrics.chipHeight)
                .foregroundStyle(isActive ? Color.preferredText(on: tint) : Color.secondary)
                .background(isActive ? tint : Color.lsCard, in: Capsule())
                .overlay { Capsule().stroke(Color.lsBorder, lineWidth: isActive ? 0 : 1) }
        }
        .buttonStyle(.plain)
        .contentShape(Capsule())
        .accessibilityAddTraits(isActive ? [.isSelected] : [])
    }
}
#endif
