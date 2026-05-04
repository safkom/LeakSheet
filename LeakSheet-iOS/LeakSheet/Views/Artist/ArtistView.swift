import SwiftUI

/// Artist detail screen — stats, search/filter, era cards, song lists.
struct ArtistView: View {
    let artist: Artist

    @State private var vm: ArtistViewModel
    @State private var showDescription: DescriptionSheet.Payload?
    @State private var showQueue = false
    @State private var eraColors: [String: Color] = [:]
    @State private var activeEraColor: Color?
    @State private var showSearch = false
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
                    // Large artist name header
                    HStack(spacing: 0) {
                        Text(artist.name)
                            .font(.title2.weight(.bold))
                            .foregroundStyle((activeEraColor ?? .primary).ensureReadable(against: .lsBackground))
                        Spacer()
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                    .padding(.bottom, 4)

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

                    // Content
                    if vm.recents {
                        recentsList
                    } else {
                        erasList(proxy: proxy)
                    }

                    // Bottom padding for mini player
                    if player.currentTrack != nil {
                        Color.clear.frame(height: 100)
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
        }
        .overlay {
            if showSearch {
                SearchOverlayView(
                    search: { vm.searchResults(for: $0) },
                    artistName: artist.name,
                    artistSlug: artist.slug,
                    sourceUrl: artist.sourceUrl,
                    onShowDescription: { payload in
                        showDescription = payload
                        withAnimation(reduceMotion ? nil : .spring(duration: 0.3)) { showSearch = false }
                    },
                    onDismiss: {
                        withAnimation(reduceMotion ? nil : .spring(duration: 0.3)) { showSearch = false }
                    }
                )
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(reduceMotion ? nil : .spring(duration: 0.35), value: showSearch)
        .toolbarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) {
                VStack(spacing: 1) {
                    Text(artist.name)
                        .font(.headline.weight(.bold))
                        .foregroundStyle((activeEraColor ?? .primary).ensureReadable(against: .lsBackground))
                        .lineLimit(1)
                    Text("\(vm.artistStats.total) tracks")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            ToolbarItemGroup(placement: .topBarTrailing) {
                GlassEffectContainer {
                    HStack(spacing: 4) {
                        Button {
                            withAnimation(reduceMotion ? nil : .spring(duration: 0.35)) {
                                showSearch = true
                            }
                        } label: {
                            Image(systemName: "magnifyingglass")
                                .frame(width: 36, height: 36)
                                .accessibilityHidden(true)
                        }
                        .glassEffect(.regular.interactive(), in: .circle)
                        .accessibilityLabel("Search songs")
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
        }
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
            for (eraName, color) in vm.prefetchedColors {
                eraColors[eraName] = color
            }
            // Register ordered era list with the engine so playback auto-continues
            // to the next era when the current one runs out.
            let eraContexts = artist.eras.map { era in
                EraSongContext(
                    eraName: era.name,
                    artistName: artist.name,
                    artUrl: era.artUrl ?? "",
                    versions: era.allSongs.flatMap(\.versions).filter(\.isStreamable)
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

    // MARK: - Filter toggles

    private var filterToggles: some View {
        ScrollView(.horizontal, showsIndicators: false) {
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
                            .foregroundStyle(eraColors[result.era.name] ?? .secondary)
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
                        player.playTrack(result.version, artistName: artist.name, eraName: result.era.name, artUrl: result.era.artUrl ?? "")
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

// MARK: - Search overlay

struct SearchOverlayView: View {
    /// Called with the trimmed query — returns ranked results without touching filteredEras.
    var search: (String) -> [ArtistViewModel.SearchResult]
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    var onShowDescription: (DescriptionSheet.Payload) -> Void
    var onDismiss: () -> Void

    @State private var query = ""
    @State private var results: [ArtistViewModel.SearchResult] = []
    @FocusState private var focused: Bool
    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .top) {
                // Near-solid background for readability
                Color.lsBackground.opacity(0.97)
                    .ignoresSafeArea(.all)
                    .ignoresSafeArea(.keyboard)
                    .onTapGesture { onDismiss() }

                VStack(spacing: 0) {
                    // Liquid glass search bar at top
                    HStack(spacing: 12) {
                        Image(systemName: "magnifyingglass")
                            .foregroundStyle(.secondary)
                        TextField("Search songs...", text: $query)
                            .focused($focused)
                            .textFieldStyle(.plain)
                            .autocorrectionDisabled()
                            .submitLabel(.search)
                        if !query.isEmpty {
                            Button {
                                query = ""
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(.secondary)
                            }
                            .buttonStyle(.plain)
                        }
                        Button("Done") {
                            onDismiss()
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.lsAccent)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                    .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 18))
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                    .padding(.bottom, 8)

                    // Results area
                    if !query.isEmpty {
                        if results.isEmpty {
                            VStack(spacing: 10) {
                                Image(systemName: "magnifyingglass")
                                    .font(.title2)
                                    .foregroundStyle(.tertiary)
                                Text("No results for \"\(query)\"")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 32)
                            .transition(.opacity)
                        } else {
                            ScrollView {
                                LazyVStack(spacing: 0) {
                                    Text("\(results.count) result\(results.count == 1 ? "" : "s")")
                                        .font(.caption.weight(.medium))
                                        .foregroundStyle(.secondary)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .padding(.horizontal, 16)
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
                                                player.playTrack(result.version, artistName: artistName, eraName: result.era.name, artUrl: result.era.artUrl ?? "")
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
                                .padding(.top, 4)
                                .padding(.bottom, 8)
                            }
                            .transition(.opacity.combined(with: .move(edge: .top)))
                        }
                    }

                    Spacer()
                }
                .animation(.spring(duration: 0.3), value: results.count)
                .animation(.spring(duration: 0.3), value: query.isEmpty)
            }
        }
        // Debounce: wait 200ms after last keystroke before searching
        .task(id: query) {
            guard !query.isEmpty else {
                results = []
                return
            }
            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled else { return }
            results = search(query)
        }
        .task {
            // Delay focus until the slide-up animation completes
            try? await Task.sleep(for: .milliseconds(350))
            focused = true
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
                .glassEffect(isActive ? .regular.tint(tintColor).interactive() : .regular.interactive())
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
