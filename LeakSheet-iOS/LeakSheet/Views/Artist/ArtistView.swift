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
    /// View model built during the landing screen's own loading state, so the
    /// pushed screen renders content on its first frame instead of showing a
    /// second "Preparing…" spinner. Nil only for entry points that push an
    /// artist without preparing one first.
    var preparedVM: ArtistViewModel?
    @State private var displayed: Artist?
    @State private var vm: ArtistViewModel?
    @State private var lastUpdated: Date?
    /// Pull-to-refresh goes through the same loader as the landing screen, so
    /// it keeps the artist's name (favourites key on its slug), falls back to
    /// the saved copy on a server error, and reports failure instead of
    /// silently ending the refresh.
    @State private var refresher = TrackerLoader()
    @Environment(RecentTrackersManager.self) private var recents

    /// The artist currently shown — the pushed value until a pull-to-refresh
    /// swaps in freshly-fetched data.
    private var current: Artist { displayed ?? artist }

    var body: some View {
        Group {
            if let vm = vm ?? preparedVM {
                ArtistContentView(
                    artist: current, vm: vm,
                    lastUpdated: lastUpdated,
                    onRefresh: refresh
                )
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
                displayed = artist
                // Already prepared upstream in the common path; only build
                // here for entry points that pushed without preparing.
                if let preparedVM {
                    vm = preparedVM
                } else {
                    vm = await ArtistViewModel.make(artist: artist)
                }
                if let url = artist.sourceUrl {
                    // Sidecar read, not the multi-MB payload — this used to
                    // land hundreds of ms after first render and insert the
                    // data-age row ABOVE the scroll position, shunting the
                    // whole list down mid-gesture.
                    lastUpdated = await CacheService.shared.getCachedMeta(for: url)?.timestamp
                }
            }
            // The first screenful was warmed (art AND colour) before this
            // screen was pushed — see ArtistViewModel.make. Warm the rest now
            // that content is up. Cancelled when the screen goes away.
            await vm?.warmEraArt()
        }
    }

    /// Force-refetch the tracker, rebuild the view model, and stamp the data
    /// age. On failure the current data stays put and the reason is shown.
    private func refresh() async {
        guard let url = current.sourceUrl, !url.isEmpty else { return }
        let fresh = await refresher.load(url, artistName: current.name, forceRefresh: true, recents: recents)
        guard let fresh, refresher.staleNotice == nil else {
            (vm ?? preparedVM)?.loadNotice = refresher.error ?? refresher.staleNotice
            return
        }
        let refreshedVM = await ArtistViewModel.make(artist: fresh)
        displayed = fresh
        vm = refreshedVM
        lastUpdated = .now
    }
}

private struct ArtistContentView: View {
    let artist: Artist
    @Bindable var vm: ArtistViewModel
    let lastUpdated: Date?
    let onRefresh: () async -> Void

    @State private var showDescription: DescriptionSheet.Payload?
    @State private var showQueue = false
    @State private var showStats = false
    @State private var showTimeline = false
    @State private var showLegend = false
    @State private var activeEraColor: Color?
    @State private var safariItem: SafariItem?
    @State private var embedItem: EmbedItem?

    /// True when at least one era carries dated `timeline` events.
    private var hasTimeline: Bool {
        artist.eras.contains { !($0.timeline ?? []).isEmpty }
    }
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var colorScheme

    /// era name (lowercased) → art URL, first occurrence wins — mirrors the
    /// case-insensitive `.first { }` lookup misc entries used to do directly
    /// against `artist.eras`. Precomputed once so MiscListView takes a small
    /// dictionary instead of the artist's whole (potentially large) era tree.
    private let eraArtByLowercasedName: [String: String?]

    init(artist: Artist, vm: ArtistViewModel, lastUpdated: Date?, onRefresh: @escaping () async -> Void) {
        self.artist = artist
        self.vm = vm
        self.lastUpdated = lastUpdated
        self.onRefresh = onRefresh
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
                        ForEach(notices) { notice in
                            NoticeBannerView(notice: notice) { url in
                                safariItem = SafariItem(url: url)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 2)
                }

                // Stats bar — tap for the full TrackerStats breakdown.
                ArtistStatsBarView(
                    stats: vm.visibleStats,
                    unit: vm.isShowingTabEntries ? "entries" : "tracks",
                    onTap: artist.trackerStats != nil ? { showStats = true } : nil
                )

                // Data-age chip — how fresh the shown data is (pull to refresh).
                // Always occupies its line, even before the timestamp resolves:
                // appearing later inserts content above the scroll position and
                // shunts the list down under the user's finger.
                Text(vm.loadNotice ?? lastUpdated.map { "Updated \($0.formatted(.relative(presentation: .named)))" } ?? " ")
                    .font(.caption2)
                    .foregroundStyle(vm.loadNotice == nil ? Color.secondary : Color.lsError)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.top, 1)
                    .opacity(vm.loadNotice == nil && lastUpdated == nil ? 0 : 1)
                    .accessibilityHidden(vm.loadNotice == nil && lastUpdated == nil)

                // Sections first, then the filters that apply to whichever
                // section is showing. Filters only act on the song tree, so
                // they disappear on a content tab rather than sitting there
                // inert — which also keeps the header from growing a permanent
                // second row.
                ContentTabsView(vm: vm)
                    .padding(.bottom, vm.selectedTabKey == nil ? 6 : 8)

                if vm.selectedTabKey == nil {
                    FilterTogglesView(vm: vm)
                        .padding(.bottom, 8)
                }

                // Branch on computed state — see DECISIONS.md::ArtistView.swift::content-state-branching
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
                    // Fresh expansion state per tab — without this the
                    // @State set bleeds era names across tab switches.
                    .id(contentState.tabKey ?? "misc")
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
        .refreshable { await onRefresh() }
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
        // Era card gradients and header contrast are derived per appearance.
        .onChange(of: colorScheme, initial: true) { _, scheme in
            vm.setColorScheme(scheme)
        }
        .onChange(of: ObjectIdentifier(vm)) {
            vm.setColorScheme(colorScheme)
        }
        .swipeActionsContainer()
        .navigationTitle(artist.name)
        .navigationSubtitle("\(vm.visibleStats.total.formatted()) \(vm.isShowingTabEntries ? "entries" : "tracks")")
        // .large is iOS/watchOS only; a Mac window title has no large variant.
        #if os(iOS)
        .toolbarTitleDisplayMode(.large)
        #endif
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                GlassEffectContainer {
                    HStack(spacing: 8) {
                        Menu {
                            if artist.trackerStats != nil {
                                Button { showStats = true } label: { Label("Stats", systemImage: "chart.bar.xaxis") }
                            }
                            if hasTimeline {
                                Button { showTimeline = true } label: { Label("Timeline", systemImage: "clock") }
                            }
                            Button { showLegend = true } label: { Label("Badge Legend", systemImage: "info.circle") }
                        } label: {
                            Image(systemName: "ellipsis")
                                .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                                .accessibilityHidden(true)
                        }
                        .glassEffect(.regular.interactive(), in: .circle)
                        .accessibilityLabel("More")

                        Button {
                            showQueue = true
                        } label: {
                            Image(systemName: "list.bullet")
                                .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                                .accessibilityHidden(true)
                        }
                        .glassEffect(.regular.interactive(), in: .circle)
                        .accessibilityLabel("Queue")
                    }
                }
            }
        }
        // navigationBarDrawer + displayMode .always — see
        // DECISIONS.md::ArtistView.swift::search-field-placement
        // Both modifiers below are iOS-only: `navigationBarDrawer` and
        // `.onScrollDown` don't exist off-iOS, and neither does the
        // `.navigationBar` toolbar placement on macOS.
        #if os(iOS)
        .searchable(
            text: $vm.searchQuery,
            placement: .navigationBarDrawer(displayMode: .always),
            prompt: "Search songs…"
        )
        #if !SDK_WITHOUT_TOOLBAR_MINIMIZE
        // SDK 27.0 API that GitHub's Xcode 27 beta 6 image lacks; CI sets the
        // flag until the runner ships the release SDK. Delete the #if then.
        .toolbarMinimizeBehavior(.onScrollDown, for: .navigationBar)
        // Disabled: with a large title, search drawer and refresh control the
        // safe-area adjustment made the list jump while the bar collapsed.
        .toolbarMinimizationSafeAreaAdjustment(.disabled, for: .navigationBar)
        #endif
        #else
        .searchable(text: $vm.searchQuery, prompt: "Search songs…")
        #endif
        .sheet(item: $showDescription) { payload in
            SongDescriptionSheet(payload: payload)
                .environment(vm)  // enables the cross-era "Also in" section
        }
        .sheet(isPresented: $showQueue) {
            QueueSheet()
        }
        .sheet(isPresented: $showStats) {
            if let trackerStats = artist.trackerStats {
                TrackerStatsSheet(stats: trackerStats)
            }
        }
        .sheet(isPresented: $showTimeline) {
            TrackerTimelineSheet(artist: artist)
        }
        .sheet(isPresented: $showLegend) {
            BadgeLegendSheet()
        }
        .webSheet(item: $safariItem)
        .sheet(item: $embedItem) { item in
            EmbedPlayerView(item: item)
        }
        // Keyed on the view model so a pull-to-refresh, which swaps in a new
        // one, re-registers its eras instead of leaving the old song lists.
        .task(id: ObjectIdentifier(vm)) {
            // Prebuilt off-main in Precomputed — this used to walk every
            // version of every era on the MainActor, on every appearance.
            player.setArtistEras(vm.eraPlaybackContexts)
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
