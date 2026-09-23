#if os(macOS)
import SwiftUI

/// Mac shell: a source-list sidebar over a detail column, with the player bar
/// pinned to the window bottom and a Details/Queue inspector on the trailing edge.
/// See DECISIONS.md::MacRootView.swift::selection-shell.
struct MacRootView: View {
    @Environment(RecentTrackersManager.self) private var recents

    @State private var ui = MacUIState.shared
    @State private var loader = TrackerLoader()

    /// The view model for whatever is playing — lets the mini player resolve the
    /// full song behind the bare version the player holds.
    private var vmForCurrentPlayback: ArtistViewModel? {
        ui.trackers[PlayerViewModel.shared.artistSlug]?.vm
    }

    /// The view model the Details panel resolves against: the tracker being BROWSED,
    /// falling back to the one playing (a favourite of a tracker that isn't open).
    private var vmForInspector: ArtistViewModel? {
        if let slug = ui.selectedSlug, let vm = ui.tracker(slug)?.vm { return vm }
        return vmForCurrentPlayback
    }

    var body: some View {
        NavigationSplitView {
            MacSidebar(selection: $ui.selection)
        } detail: {
            // GeometryReader clamps the detail column to its offered size: see
            // DECISIONS.md::MacRootView.swift::geometry-clamp
            GeometryReader { proxy in
                detail
                    .frame(width: proxy.size.width, height: proxy.size.height, alignment: .top)
            }
            .background(Color.lsBackground)
        }
        .frame(minWidth: 900, minHeight: 620)
        .inspector(isPresented: $ui.showInspector) {
            MacInspector()
                .environment(PlayerViewModel.shared)
                .environment(FavouritesManager.shared)
                .environment(vmForInspector)
                .inspectorColumnWidth(min: 280, ideal: 340, max: 460)
        }
        .safeAreaBar(edge: .bottom) {
            MiniPlayerBar()
                .environment(PlayerViewModel.shared)
                .environment(vmForCurrentPlayback)
        }
        // ⇧⌘V routes a pasted URL into the Browse pane and loads it.
        .onChange(of: ui.pastedURL) { _, pasted in
            guard let pasted else { return }
            ui.pastedURL = nil
            ui.selection = .browse
            loader.url = pasted
            Task { await open(pasted) }
        }
        // Selecting a tracker that isn't parsed yet (a sidebar row from a
        // previous launch) loads it on demand.
        .onChange(of: ui.selection) { _, selection in
            // The Details panel is scoped to what you are looking at, so a stale song
            // can't resolve against another tracker's era tree.
            ui.selectedSong = nil
            if case .tracker(let slug) = selection { ui.touch(slug) }
            guard case .tracker(let slug) = selection, ui.tracker(slug) == nil,
                  let entry = recents.trackers.first(where: { $0.slug == slug })
            else { return }
            Task { await open(entry.sourceUrl, artistName: entry.name, select: false) }
        }
        // ⌘R re-fetches the selected tracker, bypassing the cache.
        .onChange(of: ui.refreshToken) { _, _ in
            guard let slug = ui.selectedSlug,
                  let url = ui.tracker(slug)?.artist.sourceUrl
                    ?? recents.trackers.first(where: { $0.slug == slug })?.sourceUrl
            else { return }
            Task { await open(url, forceRefresh: true, select: false) }
        }
    }

    // MARK: - Detail column

    @ViewBuilder
    private var detail: some View {
        switch ui.selection {
        case .browse, nil:
            browsePane
        case .favourites:
            // onShowDescription routes into the inspector, the same surface song rows use.
            FavouritesView(
                embedded: true,
                onShowDescription: { payload in
                    ui.selectedSong = payload
                    ui.inspectorTab = .details
                    ui.showInspector = true
                }
            )
            .environment(FavouritesManager.shared)
            .environment(vmForCurrentPlayback)
        case .tracker(let slug):
            if let loaded = ui.tracker(slug) {
                MacArtistView(artist: loaded.artist, vm: loaded.vm)
                    .id(slug)
            } else {
                loadingPane
            }
        }
    }

    private var loadingPane: some View {
        VStack(spacing: 10) {
            ProgressView()
            if let error = loader.error {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(Color.lsError)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
            } else {
                Text("Loading tracker…")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var browsePane: some View {
        VStack(spacing: 0) {
            TrackerInputView(
                url: $loader.url,
                loading: loader.loading,
                loadPhase: loader.loadPhase
            ) {
                await open(loader.url)
            }
            .padding(16)
            .frame(maxWidth: Metrics.contentMaxWidth)

            if let error = loader.error {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(Color.lsError)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 8)
            }

            Divider().overlay(Color.lsBorder)

            // embedded: the split view already supplies the title and toolbar.
            BrowseArtistsView(
                onPick: { pickedUrl, pickedName in
                    Task { await open(pickedUrl, artistName: pickedName) }
                },
                embedded: true
            )
        }
        .navigationTitle("Browse")
    }

    // MARK: - Loading

    /// Fetch, parse, build the view model, and file the result under its slug.
    /// One loading state per tracker, matching iOS — the view model is built
    /// inside `preparing` so there is no second "Preparing…" spinner.
    private func open(
        _ url: String,
        artistName: String? = nil,
        forceRefresh: Bool = false,
        select: Bool = true
    ) async {
        guard let artist = await loader.load(
            url, artistName: artistName, forceRefresh: forceRefresh, recents: recents
        ) else { return }
        let vm = await loader.preparing { await ArtistViewModel.make(artist: artist) }
        ui.store(LoadedTracker(artist: artist, vm: vm))
        if select || ui.selectedSlug != artist.slug {
            ui.selection = .tracker(slug: artist.slug)
        }
    }
}
#endif
