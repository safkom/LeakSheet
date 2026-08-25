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
    @State private var lastUpdated: Date?
    @State private var showStats = false
    @State private var showTimeline = false
    @State private var showLegend = false
    @State private var safariItem: SafariItem?
    @State private var embedItem: EmbedItem?

    @Environment(PlayerViewModel.self) private var player
    @Environment(\.colorScheme) private var colorScheme

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
    ///
    /// Reads the view model's own `expandedEra` rather than keeping a second
    /// copy. It used to shadow it in `MacUIState`, and the two desynced:
    /// turning the LAST badge filter off makes `toggleBestOf` clear
    /// `expandedEra`, so the shadow still named an era while the view model had
    /// no era expanded — the page rendered "No Songs" for an era full of them.
    private var openEra: String? {
        isFlatMode ? nil : vm.expandedEra
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
        // Computed ONCE per body evaluation and handed down. As a computed
        // property it was re-derived at every use site — six of them.
        let rows = visibleRows
        content(rows)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
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
        // Era card gradients and header contrast are derived per appearance.
        .onChange(of: colorScheme, initial: true) { _, scheme in
            vm.setColorScheme(scheme)
        }
        // Keyed on the view model's identity, not the slug: ⌘R replaces the
        // parsed tracker in place, so a slug-keyed task never re-fired and the
        // "Updated …" stamp and playback contexts stayed on the old parse.
        .task(id: ObjectIdentifier(vm)) {
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

    // MARK: - Page header

    /// Scrolls with the content rather than sitting above it.
    ///
    /// Pinned, it cost ~290pt of a 700pt window — and on an era page it showed
    /// the WHOLE tracker's totals (9,343) under a title reading "77 songs",
    /// which answers a question nobody asked on that page.
    @ViewBuilder
    private var pageHeader: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let openEra {
                eraHeader(openEra)
            } else {
                trackerHeader
            }

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
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .padding(.bottom, 10)
    }

    /// Tracker-level chrome, shown on the era grid.
    @ViewBuilder
    private var trackerHeader: some View {
        if let notices = artist.notices, !notices.isEmpty {
            VStack(spacing: 4) {
                ForEach(notices) { notice in
                    NoticeBannerView(notice: notice) { safariItem = SafariItem(url: $0) }
                }
            }
        }
        statRow(vm.artistStats)
        if let lastUpdated {
            Text("Updated \(lastUpdated.formatted(.relative(presentation: .named)))")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    /// Era-level chrome: cover, name, and the era's own numbers — plus the Play
    /// action the page was missing entirely (starting an era meant finding a
    /// song in it and double-clicking that).
    @ViewBuilder
    private func eraHeader(_ name: String) -> some View {
        let filtered = vm.filteredEra(named: name)
        HStack(alignment: .center, spacing: 14) {
            Group {
                if let artUrl = filtered?.era.artUrl,
                   let url = APIClient.shared.imageProxyURL(for: artUrl, width: 240) {
                    CachedImage(url: url, maxPixelSize: 240) { ArtworkPlaceholder(cornerRadius: 0) }
                } else {
                    ArtworkPlaceholder(cornerRadius: 0)
                }
            }
            .frame(width: 72, height: 72)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 4) {
                Text(name)
                    .font(.title2.weight(.semibold))
                    .lineLimit(2)
                if let alts = filtered?.era.altNames, !alts.isEmpty {
                    Text(alts.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if let stats = filtered?.stats {
                    Text("\(stats.total) tracks · \(stats.available) available · \(stats.snippets) snippets")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer(minLength: 8)

            if let filtered, !filtered.streamableVersions.isEmpty {
                Button {
                    guard let first = filtered.streamableVersions.first else { return }
                    player.playInEra(
                        first, eraName: name, artistName: artist.name,
                        artUrl: filtered.era.artUrl ?? "",
                        versions: filtered.streamableVersions, artistSlug: artist.slug
                    )
                } label: {
                    Label("Play", systemImage: "play.fill")
                }
                .buttonStyle(.borderedProminent)
                .help("Play this era")
            }
        }

        if let desc = filtered?.era.description, !desc.isEmpty {
            Text(desc)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// Compact stat row. The four tiles were `maxWidth: .infinity`, stretching
    /// a glanceable summary across the whole window.
    private func statRow(_ stats: ArtistViewModel.Stats) -> some View {
        HStack(spacing: 8) {
            statTile(stats.total, "Total", .secondary)
            statTile(stats.available, "Available", .green)
            statTile(stats.snippets, "Snippets", .orange)
            statTile(stats.fullHQ, "Full HQ", .lsAccent)
        }
    }

    private func statTile(_ value: Int, _ label: String, _ color: Color) -> some View {
        VStack(spacing: 1) {
            Text("\(value)")
                .font(.subheadline.weight(.semibold).monospacedDigit())
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(minWidth: 76)
        .padding(.vertical, 6)
        .background(Color.lsCard, in: RoundedRectangle(cornerRadius: 8))
    }

    @ToolbarContentBuilder
    private var toolbarItems: some ToolbarContent {
        ToolbarItemGroup {
            if openEra != nil {
                Button {
                    vm.openEra(nil)
                    ui.selectedSong = nil
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
    private func content(_ rows: [MacListRow]) -> some View {
        if vm.isFiltering && rows.isEmpty && !isMiscMode {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if isMiscMode {
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
        } else if openEra == nil && !isFlatMode {
            ScrollView {
                VStack(spacing: 0) {
                    pageHeader
                    MacEraGrid(vm: vm) { eraName in
                        vm.openEra(eraName)
                        ui.selectedSong = nil
                    }
                }
                .frame(maxWidth: Metrics.contentMaxWidth)
                .frame(maxWidth: .infinity)
            }
        } else if rows.isEmpty {
            VStack(spacing: 0) {
                pageHeader
                    .frame(maxWidth: Metrics.contentMaxWidth)
                emptyState
            }
        } else {
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
    private var visibleRows: [MacListRow] {
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
    private func play(_ version: SongVersion, eraName: String, in rows: [MacListRow]) {
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
