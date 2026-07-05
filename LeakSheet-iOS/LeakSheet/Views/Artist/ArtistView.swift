import SwiftUI

/// Artist detail screen — stats, search/filter, era cards, song lists.
struct ArtistView: View {
    let artist: Artist

    @State private var vm: ArtistViewModel
    @State private var showDescription: DescriptionSheet.Payload?
    @State private var showQueue = false
    @State private var eraColors: [String: Color] = [:]
    @State private var activeEraColor: Color?
    @State private var recentsDisplayCount = 60
    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(artist: Artist) {
        self.artist = artist
        self._vm = State(initialValue: ArtistViewModel(artist: artist))
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 0) {
                    // Notices
                    if let notices = artist.notices, !notices.isEmpty {
                        VStack(spacing: 4) {
                            ForEach(Array(notices.enumerated()), id: \.offset) { _, notice in
                                NoticeBannerView(notice: notice)
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 2)
                    }

                    // Stats bar
                    ArtistStatsBarView(stats: vm.artistStats)

                    // Filter toggles
                    filterToggles
                        .padding(.bottom, 8)

                    // Content: Misc is a strict mode (never mixed with era
                    // songs; search/chips filter within it), then search
                    // results take priority over eras/recents.
                    if vm.misc {
                        miscList
                    } else if vm.isSearching {
                        searchResultsList
                    } else if vm.recents {
                        recentsList
                    } else {
                        erasList(proxy: proxy)
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
            .swipeActionsContainer()
        }
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
            // System search item in the nav bar — keeps the search affordance
            // out of the bottom slot where the mini player (safeAreaBar) lives.
            DefaultToolbarItem(kind: .search, placement: .topBarTrailing)
        }
        .searchable(
            text: Binding(get: { vm.searchQuery }, set: { vm.searchQuery = $0 }),
            prompt: "Search songs…"
        )
        .toolbarMinimizeBehavior(.onScrollDown, for: .navigationBar)
        .sheet(item: $showDescription) { payload in
            SongDescriptionSheet(payload: payload)
        }
        .sheet(isPresented: $showQueue) {
            QueueSheet()
        }
        .task {
            await withTaskGroup(of: Void.self) { group in
                group.addTask { await self.vm.prefetchEraImages() }
                group.addTask { try? await Task.sleep(for: .seconds(5)) }
                await group.next()
                group.cancelAll()
            }
            // Single assignment — per-key writes invalidate every visible
            // era card's glass effect once per key, all in the same frame.
            eraColors = eraColors.merging(vm.prefetchedColors) { _, new in new }
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
            if activeEraColor == nil {
                if let first = artist.eras.first(where: { vm.prefetchedColors[$0.name] != nil }),
                   let color = vm.prefetchedColors[first.name] {
                    withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.4)) {
                        activeEraColor = color
                    }
                }
            }
        }
    }

    // MARK: - Search results

    @ViewBuilder
    private var searchResultsList: some View {
        let results = vm.searchResults(for: vm.debouncedQuery)
        if results.isEmpty {
            ContentUnavailableView.search(text: vm.debouncedQuery)
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
                    artistName: artist.name,
                    artistSlug: artist.slug,
                    sourceUrl: artist.sourceUrl,
                    eraName: result.era.name,
                    eraArt: result.era.artUrl,
                    showVersionBadge: true,
                    onShowDescription: { payload in showDescription = payload }
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
                        showDescription = DescriptionSheet.Payload(
                            song: result.song, version: result.version,
                            artistName: artist.name, artistSlug: artist.slug,
                            eraName: result.era.name, eraArt: result.era.artUrl
                        )
                    }
                }
                .padding(.horizontal, 16)
            }
        }
    }

    /// Start playback of the tapped entry inside its visible ordered list, so
    /// auto-advance continues down the list (search results, recents) instead
    /// of stopping after one track.
    private func playWithinList(_ entries: [(version: SongVersion, era: Era, id: String)], tappedId: String) {
        let streamable = entries.filter { $0.version.isStreamable }
        guard let idx = streamable.firstIndex(where: { $0.id == tappedId }) else { return }
        let items = streamable.map {
            PlaybackListItem(
                version: $0.version,
                artistName: artist.name,
                eraName: $0.era.name,
                artUrl: $0.era.artUrl ?? "",
                artistSlug: artist.slug
            )
        }
        player.playInList(items, startAt: idx)
    }

    // MARK: - Filter toggles

    private var filterToggles: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            // Sibling glass elements belong in one container — standalone
            // effects re-resolve independently and can trip the
            // "glassEffect() tried to update multiple times per frame" fault.
            GlassEffectContainer {
                HStack(spacing: 8) {
                    FilterChip(label: "Best Of", icon: "star.fill", isActive: vm.bestOf, tintColor: .filterBestOf) {
                        vm.toggleBestOf()
                    }
                    FilterChip(label: "Recent", icon: "clock", isActive: vm.recents, tintColor: .filterRecent) {
                        vm.toggleRecents()
                        recentsDisplayCount = 60
                    }
                    FilterChip(label: "No Snippets", icon: "waveform.slash", isActive: vm.noSnippets, tintColor: .filterNoSnippets) {
                        vm.toggleNoSnippets()
                    }
                    if vm.hasMiscEntries {
                        FilterChip(label: "Misc", icon: "film.stack", isActive: vm.misc, tintColor: .filterMisc) {
                            vm.toggleMisc()
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
        }
    }

    // MARK: - Eras list

    @ViewBuilder
    private func erasList(proxy: ScrollViewProxy) -> some View {
        ForEach(vm.filteredEras, id: \.name) { era in
            let eraColor = eraColors[era.name]
            let isExpanded = vm.isEraExpanded(era.name)

            VStack(spacing: 0) {
                // Era card — 16pt inset from screen edges
                EraCardView(
                    era: era,
                    expanded: isExpanded,
                    stats: vm.eraStats(era),
                    onTap: {
                        withAnimation(reduceMotion ? nil : .spring(duration: 0.3, bounce: 0.1)) {
                            vm.toggleEra(era.name)
                        }
                    },
                    onColorExtracted: { color in
                        eraColors[era.name] = color
                        if activeEraColor == nil {
                            withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.4)) {
                                activeEraColor = color
                            }
                        }
                    }
                )
                .padding(.horizontal, 16)
                .id("era-\(era.name)")

                if isExpanded {
                    // 2pt accent divider — same width as card
                    Rectangle()
                        .fill(eraColor ?? Color.lsAccent)
                        .frame(height: 2)
                        .padding(.horizontal, 16)

                    // Songs panel — exactly same horizontal position as era card
                    SongListView(
                        era: era,
                        sections: vm.filteredSections(for: era),
                        songs: vm.filteredSongs(for: era),
                        artistName: artist.name,
                        artistSlug: artist.slug,
                        sourceUrl: artist.sourceUrl,
                        eraColor: eraColor,
                        onShowDescription: { payload in showDescription = payload }
                    )
                    .background(eraColor?.opacity(0.08) ?? Color.clear)
                    .clipShape(
                        UnevenRoundedRectangle(
                            bottomLeadingRadius: 16,
                            bottomTrailingRadius: 16
                        )
                    )
                    .padding(.horizontal, 16)
                }
            }
            // Gap between eras
            .padding(.bottom, 12)
        }
    }

    // MARK: - Misc entries

    @ViewBuilder
    private var miscList: some View {
        let entries = vm.miscResults

        if entries.isEmpty {
            ContentUnavailableView(
                "No Misc Entries",
                systemImage: "film.stack",
                description: Text("Nothing matches the current filters.")
            )
            .padding(.top, 40)
        } else {
            ForEach(Array(entries.enumerated()), id: \.element.id) { idx, entry in
                // Era group header — shown when the era changes
                if idx == 0 || entries[idx - 1].eraName != entry.eraName {
                    HStack(spacing: 8) {
                        Text(entry.eraName.isEmpty ? "OTHER" : entry.eraName.uppercased())
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle((eraColors[entry.eraName] ?? .secondary).ensureReadable(against: .lsBackground))
                        Rectangle()
                            .fill(Color.lsBorder)
                            .frame(height: 1)
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, idx == 0 ? 4 : 12)
                    .padding(.bottom, 2)
                }

                MiscEntryRowView(entry: entry) { payload in
                    showDescription = payload
                }
                .contentShape(Rectangle())
                .accessibilityAddTraits(.isButton)
                .onTapGesture {
                    handleMiscTap(entry, in: entries)
                }
                .padding(.horizontal, 16)
            }
        }
    }

    /// Streamable entries play with continuation across the misc list;
    /// non-streamable entries open their link externally, and link-less
    /// entries show the description sheet.
    private func handleMiscTap(_ entry: MiscEntry, in entries: [MiscEntry]) {
        if entry.isStreamable {
            Haptics.light()
            let streamable = entries.filter(\.isStreamable)
            guard let idx = streamable.firstIndex(where: { $0.id == entry.id }) else { return }
            let items = streamable.map {
                PlaybackListItem(
                    version: $0.asSongVersion,
                    artistName: artist.name,
                    eraName: $0.eraName,
                    artUrl: eraArtUrl(for: $0.eraName) ?? "",
                    artistSlug: artist.slug
                )
            }
            player.playInList(items, startAt: idx)
        } else if let link = entry.links.first, let url = URL(string: link) {
            UIApplication.shared.open(url)
        } else {
            showDescription = DescriptionSheet.Payload(
                song: nil, version: entry.asSongVersion,
                artistName: artist.name, artistSlug: artist.slug,
                eraName: entry.eraName, eraArt: eraArtUrl(for: entry.eraName)
            )
        }
    }

    /// Era art for a misc entry — matched against the main-tab eras by name.
    private func eraArtUrl(for eraName: String) -> String? {
        artist.eras.first { $0.name.caseInsensitiveCompare(eraName) == .orderedSame }?.artUrl
    }

    // MARK: - Recents

    @ViewBuilder
    private var recentsList: some View {
        let allResults = vm.cachedRecentResults
        let visible = Array(allResults.prefix(recentsDisplayCount))

        if vm.recentsLoading && visible.isEmpty {
            ProgressView()
                .frame(maxWidth: .infinity)
                .padding(.vertical, 32)
        } else {
            ForEach(Array(visible.enumerated()), id: \.element.id) { idx, result in
                // Era group header — show when era changes
                if idx == 0 || visible[idx - 1].era.name != result.era.name {
                    HStack(spacing: 8) {
                        Text(result.era.name.uppercased())
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle((eraColors[result.era.name] ?? .secondary).ensureReadable(against: .lsBackground))
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
                    artistName: artist.name,
                    artistSlug: artist.slug,
                    sourceUrl: artist.sourceUrl,
                    eraName: result.era.name,
                    eraArt: result.era.artUrl,
                    showVersionBadge: true,
                    onShowDescription: { payload in showDescription = payload }
                )
                .contentShape(Rectangle())
                .accessibilityAddTraits(.isButton)
                .onTapGesture {
                    if result.version.isStreamable {
                        Haptics.light()
                        // Continue down the full recents list, not just the
                        // currently rendered prefix.
                        playWithinList(
                            allResults.map { (version: $0.version, era: $0.era, id: $0.id) },
                            tappedId: result.id
                        )
                    } else {
                        showDescription = DescriptionSheet.Payload(
                            song: result.song, version: result.version,
                            artistName: artist.name, artistSlug: artist.slug,
                            eraName: result.era.name, eraArt: result.era.artUrl
                        )
                    }
                }
                .padding(.horizontal, 16)
                .onAppear {
                    if idx == visible.count - 1 && recentsDisplayCount < allResults.count {
                        recentsDisplayCount += 60
                    }
                }
            }
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
                .glassEffect(.regular.tint(isActive ? tintColor : .clear).interactive())
        }
        .buttonStyle(.plain)
        .frame(minHeight: 44)
        .contentShape(Capsule())
    }
}

// MARK: - Notice banner

struct NoticeBannerView: View {
    let notice: Notice

    private var isAlert: Bool { notice.kind == "alert" }
    private var tintColor: Color { isAlert ? .orange : Color(hex: 0x94A3B8) }
    private var bgColor: Color { isAlert ? Color.orange.opacity(0.10) : Color(hex: 0x94A3B8).opacity(0.12) }

    var body: some View {
        Button {
            if let link = notice.link, let url = URL(string: link) {
                UIApplication.shared.open(url)
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
