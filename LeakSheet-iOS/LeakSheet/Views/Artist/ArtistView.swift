import SwiftUI

/// Artist detail screen — stats, search/filter, era cards, song lists.
///
/// All list content renders as direct children of ONE LazyVStack: era cards,
/// song rows, and version rows are flattened into `vm.eraRows` so every row
/// materializes lazily. Filtering runs off-main in the view model; the body
/// only iterates prepared arrays.
///
/// Each content branch (search/misc/recents/eras) is its own `View` type with
/// narrow inputs — not a computed property — so toggling one doesn't share an
/// invalidation boundary with the others or with this screen's own `@State`.
struct ArtistView: View {
    let artist: Artist
    @State private var vm: ArtistViewModel?

    var body: some View {
        Group {
            if let vm {
                ArtistContentView(artist: artist, vm: vm)
            } else {
                // Sub-second placeholder while the stats/content pass runs
                // off-main — pushing a huge tracker no longer hitches the
                // navigation transition.
                ProgressView("Preparing…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color.lsBackground)
            }
        }
        .task(id: artist.slug) {
            if vm == nil {
                vm = await ArtistViewModel.make(artist: artist)
            }
        }
    }
}

private struct ArtistContentView: View {
    let artist: Artist
    @Bindable var vm: ArtistViewModel

    @State private var showDescription: DescriptionSheet.Payload?
    @State private var showQueue = false
    @State private var activeEraColor: Color?
    @State private var safariItem: SafariItem?
    @State private var embedItem: EmbedItem?
    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// era name (lowercased) → art URL, first occurrence wins — mirrors the
    /// case-insensitive `.first { }` lookup misc entries used to do directly
    /// against `artist.eras`. Precomputed once so MiscListView takes a small
    /// dictionary instead of the artist's whole (potentially large) era tree.
    private let eraArtByLowercasedName: [String: String?]

    init(artist: Artist, vm: ArtistViewModel) {
        self.artist = artist
        self.vm = vm
        var eraArt: [String: String?] = [:]
        for era in artist.eras {
            let key = era.name.lowercased()
            if eraArt[key] == nil { eraArt[key] = era.artUrl }
        }
        self.eraArtByLowercasedName = eraArt
    }

    /// Routes a non-stream link tap: embeddable hosts get their official
    /// in-app player, everything else opens in the in-app Safari sheet —
    /// the user is never bounced out of the app.
    private func openLink(_ link: MiscLink) {
        guard let url = URL(string: link.url) else { return }
        if link.kind == .embed, let embedURL = MiscLinkClassifier.embedURL(for: link.url) {
            embedItem = EmbedItem(originalURL: url, embedURL: embedURL, title: link.label)
        } else {
            safariItem = SafariItem(url: url)
        }
    }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                // Notices
                if let notices = artist.notices, !notices.isEmpty {
                    VStack(spacing: 4) {
                        ForEach(notices, id: \.text) { notice in
                            NoticeBannerView(notice: notice) { url in
                                safariItem = SafariItem(url: url)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 2)
                }

                // Stats bar
                ArtistStatsBarView(stats: vm.artistStats)

                // Filter toggles
                FilterTogglesView(vm: vm)
                    .padding(.bottom, 8)

                // Content branches follow the COMPUTED state (content.state),
                // not the live chip flags — the chips flip instantly while
                // the previous content stays up until the new one lands,
                // so a branch never renders data computed for another mode.
                let contentState = vm.content.state
                if contentState.misc || contentState.tabKey != nil {
                    MiscListView(
                        vm: vm,
                        artistName: artist.name,
                        artistSlug: artist.slug,
                        eraArtByLowercasedName: eraArtByLowercasedName,
                        onShowDescription: { showDescription = $0 },
                        onOpenLink: { openLink($0) }
                    )
                } else if !contentState.query.isEmpty {
                    SearchResultsListView(
                        vm: vm,
                        artistName: artist.name,
                        artistSlug: artist.slug,
                        sourceUrl: artist.sourceUrl,
                        onShowDescription: { showDescription = $0 }
                    )
                } else if contentState.recents {
                    RecentsListView(
                        vm: vm,
                        artistName: artist.name,
                        artistSlug: artist.slug,
                        sourceUrl: artist.sourceUrl,
                        onShowDescription: { showDescription = $0 }
                    )
                } else {
                    ErasListView(
                        vm: vm,
                        artistName: artist.name,
                        artistSlug: artist.slug,
                        sourceUrl: artist.sourceUrl,
                        onShowDescription: { showDescription = $0 },
                        onColorExtracted: { color in
                            if activeEraColor == nil {
                                withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.4)) {
                                    activeEraColor = color
                                }
                            }
                        }
                    )
                }
            }
        }
        .background(
            ZStack {
                Color.lsBackground
                if let color = activeEraColor {
                    LinearGradient(
                        colors: [color.opacity(0.15), Color.clear],
                        startPoint: .top,
                        endPoint: UnitPoint(x: 0.5, y: 0.7)
                    )
                    .ignoresSafeArea()
                    .animation(reduceMotion ? nil : .easeInOut(duration: 0.5), value: activeEraColor)
                }
            }
        )
        // Bottom-anchored so it can't hide behind the nav bar or the search
        // drawer (the old top anchor sat underneath both).
        .overlay(alignment: .bottom) {
            if vm.isFiltering {
                ProgressView()
                    .controlSize(.small)
                    .padding(8)
                    .background(.thinMaterial, in: Capsule())
                    .padding(.bottom, 12)
                    .transition(.opacity)
            }
        }
        .swipeActionsContainer()
        .navigationTitle(artist.name)
        .navigationSubtitle("\(vm.artistStats.total) tracks")
        .toolbarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                GlassEffectContainer {
                    Button {
                        showQueue = true
                    } label: {
                        Image(systemName: "list.bullet")
                            .frame(width: 36, height: 36)
                            .accessibilityHidden(true)
                    }
                    .glassEffect(.regular.interactive(), in: .circle)
                    .accessibilityLabel("Queue")
                }
            }
        }
        // navigationBarDrawer pins the search field under the navigation bar
        // at the TOP of the screen. The default iPhone placement (and the
        // toolbar search item's minimized form) both live in the bottom slot,
        // where they end up behind the mini player (safeAreaBar) — the drawer
        // is the one placement that can never collide with it.
        // displayMode .always: the .automatic drawer minimizes into a bare
        // black capsule behind the Dynamic Island once content scrolls
        // (audited 2026-07-13) — keeping the field visible avoids the
        // glitch-looking pill and makes search discoverable.
        .searchable(
            text: $vm.searchQuery,
            placement: .navigationBarDrawer(displayMode: .always),
            prompt: "Search songs…"
        )
        .toolbarMinimizeBehavior(.onScrollDown, for: .navigationBar)
        .sheet(item: $showDescription) { payload in
            SongDescriptionSheet(payload: payload)
        }
        .sheet(isPresented: $showQueue) {
            QueueSheet()
        }
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
        .sheet(item: $embedItem) { item in
            EmbedPlayerView(item: item)
        }
        .task {
            // Register ordered era list with the engine so playback auto-continues
            // to the next era when the current one runs out.
            let eraContexts = artist.eras.map { era in
                EraSongContext(
                    eraName: era.name,
                    artistName: artist.name,
                    artUrl: era.artUrl ?? "",
                    versions: era.allSongs.flatMap(\.versions).filter(\.isStreamable),
                    artistSlug: artist.slug
                )
            }
            player.setArtistEras(eraContexts)
            // Seeded colors (from the persisted extraction cache) give the
            // background tint immediately; otherwise the first per-card
            // extraction callback sets it.
            if activeEraColor == nil {
                if let first = artist.eras.first(where: { vm.eraDisplay[$0.name] != nil }) {
                    activeEraColor = vm.eraDisplay[first.name]?.dominant
                }
            }
        }
    }
}

// MARK: - Filter toggles

/// @Observable reference input — the narrow-inputs rule for value types
/// doesn't apply here; per-property observation tracking already scopes
/// this view's invalidation to exactly the flags it reads.
private struct FilterTogglesView: View {
    let vm: ArtistViewModel

    static func tabIcon(for kind: String) -> String {
        switch kind {
        case "misc": return "film.stack"
        case "music_videos": return "video"
        case "released": return "music.note.list"
        case "best_of": return "star.circle"
        case "worst_of": return "hand.thumbsdown"
        case "stems": return "waveform.path"
        default: return "square.grid.2x2"
        }
    }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            // Sibling glass elements belong in one container — standalone
            // effects re-resolve independently and can trip the
            // "glassEffect() tried to update multiple times per frame" fault.
            GlassEffectContainer {
                HStack(spacing: 8) {
                    FilterChip(label: "Best Of", icon: "star.fill", isActive: vm.bestOf, tintColor: .filterBestOf) {
                        vm.toggleBestOf()
                    }
                    FilterChip(label: "Worst Of", icon: "hand.thumbsdown", isActive: vm.worstOf, tintColor: .filterBestOf) {
                        vm.toggleWorstOf()
                    }
                    FilterChip(label: "Recent", icon: "clock", isActive: vm.recents, tintColor: .filterRecent) {
                        vm.toggleRecents()
                    }
                    FilterChip(label: "No Snippets", icon: "waveform.slash", isActive: vm.noSnippets, tintColor: .filterNoSnippets) {
                        vm.toggleNoSnippets()
                    }
                    if !vm.availableTabs.isEmpty {
                        // One chip per parsed content tab (Misc, Music
                        // Videos, Released, Best Of, Stems, …), labeled with
                        // the tracker's own tab name.
                        ForEach(vm.availableTabs) { tab in
                            FilterChip(
                                label: tab.name,
                                icon: Self.tabIcon(for: tab.kind),
                                isActive: vm.selectedTabKey == tab.id,
                                tintColor: .filterMisc
                            ) {
                                vm.selectTab(tab.id)
                            }
                        }
                    } else if vm.hasMiscEntries {
                        // Older cached payloads without `tabs` keep the
                        // legacy flat Misc chip.
                        FilterChip(label: "Misc", icon: "film.stack", isActive: vm.misc, tintColor: .filterMisc) {
                            vm.toggleMisc()
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
        }
    }
}

// MARK: - Search results

private struct SearchResultsListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        let results = vm.content.searchResults
        if results.isEmpty {
            ContentUnavailableView.search(text: vm.content.state.query)
                .padding(.top, 40)
        } else {
            Text("\(results.count) result\(results.count == 1 ? "" : "s")")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16)
                .padding(.top, 4)
                .padding(.bottom, 4)

            ForEach(results) { result in
                SongRowView(
                    song: result.song,
                    version: result.version,
                    artistName: artistName,
                    artistSlug: artistSlug,
                    sourceUrl: sourceUrl,
                    eraName: result.era.name,
                    eraArt: result.era.artUrl,
                    showVersionBadge: true,
                    onShowDescription: onShowDescription
                )
                .contentShape(Rectangle())
                .accessibilityAddTraits(.isButton)
                .onTapGesture {
                    if result.version.isStreamable {
                        Haptics.light()
                        playWithinList(
                            results.map { (version: $0.version, era: $0.era, id: $0.id) },
                            tappedId: result.id
                        )
                    } else {
                        onShowDescription(DescriptionSheet.Payload(
                            song: result.song, version: result.version,
                            artistName: artistName, artistSlug: artistSlug,
                            eraName: result.era.name, eraArt: result.era.artUrl
                        ))
                    }
                }
                .padding(.horizontal, 16)
            }
        }
    }

    /// Start playback of the tapped entry inside its visible ordered list, so
    /// auto-advance continues down the list (search results) instead of
    /// stopping after one track.
    private func playWithinList(_ entries: [(version: SongVersion, era: Era, id: String)], tappedId: String) {
        let streamable = entries.filter { $0.version.isStreamable }
        guard let idx = streamable.firstIndex(where: { $0.id == tappedId }) else { return }
        let items = streamable.map {
            PlaybackListItem(
                version: $0.version,
                artistName: artistName,
                eraName: $0.era.name,
                artUrl: $0.era.artUrl ?? "",
                artistSlug: artistSlug
            )
        }
        player.playInList(items, startAt: idx)
    }
}

// MARK: - Eras list (flattened lazy rows)

private struct ErasListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onShowDescription: (DescriptionSheet.Payload) -> Void
    let onColorExtracted: (Color) -> Void

    @Environment(PlayerViewModel.self) private var player
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ForEach(vm.eraRows) { row in
            EraRowView(
                row: row,
                displayColors: vm.eraDisplay[row.eraName],
                artistName: artistName,
                artistSlug: artistSlug,
                sourceUrl: sourceUrl,
                onCardTap: { eraName in
                    withAnimation(reduceMotion ? nil : .spring(duration: 0.3, bounce: 0.1)) {
                        vm.toggleEra(eraName)
                    }
                },
                onColorExtracted: { eraName, color in
                    vm.setEraColor(eraName: eraName, dominant: color)
                    onColorExtracted(color)
                },
                onSongTap: handleSongTap,
                onPlayVersion: playWithEraContext,
                onShowDescription: onShowDescription
            )
        }
    }

    /// Multi-version songs expand/collapse; single-version songs play (or
    /// show the description when not streamable).
    private func handleSongTap(_ song: Song, eraName: String, eraArt: String?) {
        if song.versions.count > 1 {
            withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) {
                vm.toggleSongExpansion(eraName: eraName, baseName: song.baseName)
            }
        } else if let v = song.versions.first {
            if v.isStreamable {
                Haptics.light()
                playWithEraContext(v, eraName: eraName)
            } else {
                onShowDescription(DescriptionSheet.Payload(
                    song: song, version: v,
                    artistName: artistName, artistSlug: artistSlug,
                    eraName: eraName, eraArt: eraArt
                ))
            }
        }
    }

    /// Era-scoped playback: the filtered era's streamable versions are the
    /// auto-advance context (filtered-out versions are excluded, as before).
    private func playWithEraContext(_ version: SongVersion, eraName: String) {
        guard let filtered = vm.filteredEra(named: eraName) else { return }
        player.playInEra(
            version,
            eraName: eraName,
            artistName: artistName,
            artUrl: filtered.era.artUrl ?? "",
            versions: filtered.streamableVersions,
            artistSlug: artistSlug
        )
    }
}

// MARK: - Misc entries

private struct MiscListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    /// era name (lowercased) → art URL, precomputed once by the parent so
    /// this view doesn't need the artist's whole (potentially large) era tree.
    let eraArtByLowercasedName: [String: String?]
    let onShowDescription: (DescriptionSheet.Payload) -> Void
    /// Non-stream link taps route up to the parent, which owns the Safari
    /// and embed-player sheets.
    let onOpenLink: (MiscLink) -> Void

    @Environment(PlayerViewModel.self) private var player
    /// Expanded era groups — presentation-only, keyed on eraName. A live
    /// search expands everything so results are never hidden.
    @State private var expandedEras: Set<String> = []

    /// Entries grouped by era in order of first appearance.
    private struct EraGroup: Identifiable {
        let eraName: String
        let entries: [MiscEntry]
        var id: String { eraName }
    }

    private func eraGroups(_ entries: [MiscEntry]) -> [EraGroup] {
        var order: [String] = []
        var byEra: [String: [MiscEntry]] = [:]
        for entry in entries {
            if byEra[entry.eraName] == nil { order.append(entry.eraName) }
            byEra[entry.eraName, default: []].append(entry)
        }
        return order.map { EraGroup(eraName: $0, entries: byEra[$0] ?? []) }
    }

    private func isExpanded(_ eraName: String) -> Bool {
        vm.isSearching || expandedEras.contains(eraName)
    }

    var body: some View {
        let entries = vm.content.miscResults

        if entries.isEmpty {
            if vm.isFiltering {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 32)
            } else {
                ContentUnavailableView(
                    "No Misc Entries",
                    systemImage: "film.stack",
                    description: Text("Nothing matches the current filters.")
                )
                .padding(.top, 40)
            }
        } else {
            // Era-card accordion — the same mental model as the main eras
            // view: one collapsible card per era, entries inside.
            ForEach(eraGroups(entries)) { group in
                Button {
                    withAnimation(.default) {
                        if expandedEras.contains(group.eraName) {
                            expandedEras.remove(group.eraName)
                        } else {
                            expandedEras.insert(group.eraName)
                        }
                    }
                } label: {
                    HStack(spacing: 12) {
                        if let art = eraArtByLowercasedName[group.eraName.lowercased()] ?? nil {
                            CachedImage(url: APIClient.shared.imageProxyURL(for: art, width: 128)) {
                                Color.lsCard
                            }
                            .frame(width: 44, height: 44)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                        } else {
                            RoundedRectangle(cornerRadius: 8)
                                .fill(Color.lsCard)
                                .frame(width: 44, height: 44)
                                .overlay {
                                    Image(systemName: "music.note.list")
                                        .font(.caption)
                                        .foregroundStyle(.tertiary)
                                }
                        }
                        VStack(alignment: .leading, spacing: 2) {
                            Text(group.eraName.isEmpty ? "Other" : group.eraName)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(vm.eraDisplay[group.eraName]?.readableHeader ?? .primary)
                                .lineLimit(1)
                            Text("\(group.entries.count) entr\(group.entries.count == 1 ? "y" : "ies")")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.down")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.tertiary)
                            .rotationEffect(.degrees(isExpanded(group.eraName) ? 0 : -90))
                    }
                    .padding(12)
                    .background(Color.lsCard.opacity(0.6))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 16)
                .padding(.top, 8)

                if isExpanded(group.eraName) {
                    ForEach(group.entries) { entry in
                        MiscEntryRowView(
                            entry: entry,
                            onShowDescription: onShowDescription,
                            onSelectLink: { link in handleLinkSelection(link, for: entry, in: entries) }
                        )
                        .contentShape(Rectangle())
                        .accessibilityAddTraits(.isButton)
                        .onTapGesture {
                            handleRowTap(entry, in: entries)
                        }
                        .padding(.horizontal, 16)
                    }
                }
            }
        }
    }

    /// A single link is unambiguous, so the row's own tap performs it
    /// directly. Zero or multiple links have no one obvious action — the
    /// description sheet is the safe default, and the row's menu (built from
    /// `entry.mediaLinks`) lets the user pick a specific link explicitly.
    private func handleRowTap(_ entry: MiscEntry, in entries: [MiscEntry]) {
        let links = entry.mediaLinks
        if links.count == 1 {
            handleLinkSelection(links[0], for: entry, in: entries)
        } else {
            onShowDescription(DescriptionSheet.Payload(
                song: nil, version: entry.asSongVersion,
                artistName: artistName, artistSlug: artistSlug,
                eraName: entry.eraName, eraArt: eraArtUrl(for: entry.eraName)
            ))
        }
    }

    /// Stream-kind links play with continuation across every other
    /// stream-kind entry in the visible list, matching era/song playback;
    /// everything else (image, video, archive, generic link) opens
    /// externally — the OS decides how to handle it (Safari, a video app, a
    /// zip download).
    private func handleLinkSelection(_ link: MiscLink, for entry: MiscEntry, in entries: [MiscEntry]) {
        switch link.kind {
        case .stream:
            Haptics.light()
            let streamable = entries.filter(\.isStreamable)
            guard let idx = streamable.firstIndex(where: { $0.id == entry.id }) else { return }
            let items = streamable.map {
                PlaybackListItem(
                    version: $0.asSongVersion,
                    artistName: artistName,
                    eraName: $0.eraName,
                    artUrl: eraArtUrl(for: $0.eraName) ?? "",
                    artistSlug: artistSlug
                )
            }
            player.playInList(items, startAt: idx)
        case .image, .video, .embed, .archive, .link:
            onOpenLink(link)
        }
    }

    /// Era art for a misc entry — matched against the main-tab eras by name.
    private func eraArtUrl(for eraName: String) -> String? {
        eraArtByLowercasedName[eraName.lowercased()] ?? nil
    }
}

// MARK: - Recents

private struct RecentsListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        let visible = vm.visibleRecents

        if visible.isEmpty {
            if vm.isFiltering {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 32)
            } else {
                ContentUnavailableView(
                    "No Recent Leaks",
                    systemImage: "clock",
                    description: Text("No versions carry a leak or file date.")
                )
                .padding(.top, 40)
            }
        } else {
            ForEach(Array(visible.enumerated()), id: \.element.id) { idx, result in
                // Era group header — show when era changes
                if idx == 0 || visible[idx - 1].era.name != result.era.name {
                    HStack(spacing: 8) {
                        Text(result.era.name.uppercased())
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(vm.eraDisplay[result.era.name]?.readableHeader ?? .secondary)
                        Rectangle()
                            .fill(Color.lsBorder)
                            .frame(height: 1)
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, idx == 0 ? 4 : 12)
                    .padding(.bottom, 2)
                }

                // Date label — show only when different from previous
                let prevDate = idx > 0 ? (visible[idx - 1].version.leakDate ?? visible[idx - 1].version.fileDate) : nil
                let thisDate = result.version.leakDate ?? result.version.fileDate
                if let date = thisDate, !date.isEmpty, date != prevDate {
                    HStack(spacing: 4) {
                        Image(systemName: "calendar")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        Text(date)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                        Spacer()
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 4)
                }

                SongRowView(
                    song: result.song,
                    version: result.version,
                    artistName: artistName,
                    artistSlug: artistSlug,
                    sourceUrl: sourceUrl,
                    eraName: result.era.name,
                    eraArt: result.era.artUrl,
                    showVersionBadge: true,
                    onShowDescription: onShowDescription
                )
                .contentShape(Rectangle())
                .accessibilityAddTraits(.isButton)
                .onTapGesture {
                    if result.version.isStreamable {
                        Haptics.light()
                        // Prebuilt playback list continues down the FULL
                        // recents list, not just the rendered window.
                        if let (items, idx) = vm.recentPlayback(for: result.id) {
                            player.playInList(items, startAt: idx)
                        }
                    } else {
                        onShowDescription(DescriptionSheet.Payload(
                            song: result.song, version: result.version,
                            artistName: artistName, artistSlug: artistSlug,
                            eraName: result.era.name, eraArt: result.era.artUrl
                        ))
                    }
                }
                .padding(.horizontal, 16)
                .onAppear {
                    if idx == visible.count - 1 {
                        vm.loadMoreRecents()
                    }
                }
            }
        }
    }
}

// MARK: - Era row (flattened list)

/// Renders ONE row of the flattened era list. The body wraps its switch in a
/// single-root container so the row is unary — LazyVStack can template row
/// identity from the ForEach ids without evaluating every row's body.
private struct EraRowView: View {
    let row: EraRow
    let displayColors: EraDisplayColors?
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onCardTap: (String) -> Void
    let onColorExtracted: (String, Color) -> Void
    let onSongTap: (Song, String, String?) -> Void
    let onPlayVersion: (SongVersion, String) -> Void
    let onShowDescription: (DescriptionSheet.Payload) -> Void

    var body: some View {
        VStack(spacing: 0) {
            switch row {
            case .card(let filtered, let expanded):
                EraCardView(
                    era: filtered.era,
                    expanded: expanded,
                    stats: filtered.stats,
                    displayColors: displayColors,
                    onTap: { onCardTap(filtered.era.name) },
                    onColorExtracted: { color in onColorExtracted(filtered.era.name, color) }
                )
                .padding(.horizontal, 16)

            case .divider:
                Rectangle()
                    .fill(displayColors?.dominant ?? Color.lsAccent)
                    .frame(height: 2)
                    .padding(.horizontal, 16)

            case .groupHeader(let text, _):
                panel(isLast: false) {
                    Text(text)
                        .font(.footnote.weight(.bold))
                        .foregroundStyle(.secondary)
                        .textCase(.uppercase)
                        .padding(.top, 14)
                        .padding(.horizontal, 12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

            case .sectionHeader(let name, _, let group):
                panel(isLast: false) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(name)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(displayColors?.dominant ?? .secondary)
                            .textCase(.uppercase)
                            .tracking(0.5)
                            .padding(.horizontal, 12)
                            .frame(maxWidth: .infinity, alignment: .leading)

                        Rectangle()
                            .fill((displayColors?.dominant ?? Color.lsBorder).opacity(0.3))
                            .frame(height: 1)
                            .padding(.horizontal, 12)
                    }
                    .padding(.top, group == nil ? 14 : 6)
                }

            case .song(let song, let eraName, let eraArt, _, _, let isLast):
                panel(isLast: isLast) {
                    SongRowView(
                        song: song,
                        version: song.versions.first,
                        artistName: artistName,
                        artistSlug: artistSlug,
                        sourceUrl: sourceUrl,
                        eraName: eraName,
                        eraArt: eraArt,
                        onPlay: { onPlayVersion($0, eraName) },
                        onShowDescription: onShowDescription
                    )
                    .contentShape(Rectangle())
                    .accessibilityAddTraits(.isButton)
                    .onTapGesture {
                        onSongTap(song, eraName, eraArt)
                    }
                }

            case .version(let version, let index, let song, let eraName, let eraArt, let isLast):
                panel(isLast: isLast) {
                    VersionRowView(
                        version: version,
                        versionIndex: index,
                        artistName: artistName,
                        artistSlug: artistSlug,
                        sourceUrl: sourceUrl,
                        eraName: eraName,
                        eraArt: eraArt,
                        onPlay: { onPlayVersion($0, eraName) },
                        onShowDescription: onShowDescription
                    )
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }

            case .eraGap:
                Color.clear.frame(height: 12)
            }
        }
    }

    /// The tinted songs-panel treatment the per-era container used to apply:
    /// row-width tint, bottom corners rounded on the era's final row, 16pt
    /// screen inset.
    private func panel<Content: View>(isLast: Bool, @ViewBuilder content: () -> Content) -> some View {
        content()
            .frame(maxWidth: .infinity)
            .background(displayColors?.dominant.opacity(0.08) ?? Color.clear)
            .clipShape(
                UnevenRoundedRectangle(
                    bottomLeadingRadius: isLast ? 16 : 0,
                    bottomTrailingRadius: isLast ? 16 : 0
                )
            )
            .padding(.horizontal, 16)
    }
}

private extension EraRow {
    var eraName: String {
        switch self {
        case .card(let filtered, _): return filtered.era.name
        case .divider(let era), .eraGap(let era): return era
        case .groupHeader(_, let era): return era
        case .sectionHeader(_, let era, _): return era
        case .song(_, let era, _, _, _, _): return era
        case .version(_, _, _, let era, _, _): return era
        }
    }
}

// MARK: - Filter chip

struct FilterChip: View {
    let label: String
    let icon: String
    let isActive: Bool
    var tintColor: Color = .lsAccent
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            Label(label, systemImage: icon)
                .font(.subheadline.weight(.medium))
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .foregroundStyle(isActive ? .white : .secondary)
                // Tint via opacity keeps the glass effect structurally
                // identical across states — switching between .clear and a
                // color changed the effect identity and tripped the
                // "glassEffect() tried to update multiple times per frame"
                // fault on toggle.
                .glassEffect(.regular.tint(tintColor.opacity(isActive ? 1 : 0)).interactive())
        }
        .buttonStyle(.plain)
        .frame(minHeight: 44)
        .contentShape(Capsule())
        .accessibilityAddTraits(isActive ? [.isSelected] : [])
    }
}

// MARK: - Notice banner

struct NoticeBannerView: View {
    let notice: Notice
    /// Parent owns the presentation (in-app Safari sheet).
    var onOpenLink: (URL) -> Void

    private var isAlert: Bool { notice.kind == "alert" }
    private var tintColor: Color { isAlert ? .orange : Color(hex: 0x94A3B8) }
    private var bgColor: Color { isAlert ? Color.orange.opacity(0.10) : Color(hex: 0x94A3B8).opacity(0.12) }

    var body: some View {
        Button {
            if let link = notice.link, let url = URL(string: link) {
                onOpenLink(url)
            }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: isAlert ? "exclamationmark.triangle.fill" : "info.circle.fill")
                    .foregroundStyle(tintColor)
                Text(notice.text)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.leading)
                Spacer()
                if notice.link != nil {
                    Image(systemName: "arrow.up.right")
                        .font(.caption2)
                        .foregroundStyle(tintColor.opacity(0.7))
                }
            }
            .padding(12)
            .background(bgColor)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
        .disabled(notice.link == nil)
    }
}
