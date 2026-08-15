#if os(macOS)
import SwiftUI

/// Mac shell: a source-list sidebar over a detail column, with the player bar
/// pinned to the window bottom and the queue as a trailing inspector.
///
/// The artist screen itself (`ArtistView`) is shared with iOS verbatim — only
/// the surrounding navigation differs, because a phone's push-stack and a Mac
/// window's split view are genuinely different shapes.
struct MacRootView: View {
    enum SidebarSection: String, CaseIterable, Identifiable {
        case browse, recents, favourites, settings

        var id: String { rawValue }

        var title: String {
            switch self {
            case .browse: "Browse"
            case .recents: "Recents"
            case .favourites: "Favourites"
            case .settings: "Settings"
            }
        }

        var symbol: String {
            switch self {
            case .browse: "music.note.list"
            case .recents: "clock"
            case .favourites: "heart.fill"
            case .settings: "gearshape"
            }
        }
    }

    @Environment(RecentTrackersManager.self) private var recents

    @State private var section: SidebarSection? = .browse
    @State private var path: [Artist] = []
    @State private var loader = TrackerLoader()
    @State private var prepared: (slug: String, vm: ArtistViewModel)?
    @State private var ui = MacUIState.shared

    /// The most recently loaded artist + view model, keyed to the pushed
    /// screen. Set by every `open()`, not only ⌘R — `Artist: Hashable` is
    /// slug-only, so `path.last` can be a stale value while this holds the
    /// fresh parse. Dropped when the stack empties so a window left on the
    /// browse pane isn't retaining a whole tracker (Ye is ~9k versions).
    @State private var refreshedArtist: (artist: Artist, vm: ArtistViewModel)?
    /// Bumped per Cmd-R so the destination subtree gets a new identity.
    @State private var refreshToken = 0

    /// The prepared view model, but only when it describes the artist that is
    /// actually playing — mirrors ContentView. Lets the description sheet
    /// raised from Now Playing / Favourites resolve the full song.
    private var vmForCurrentPlayback: ArtistViewModel? {
        guard let prepared, prepared.slug == PlayerViewModel.shared.artistSlug else { return nil }
        return prepared.vm
    }

    var body: some View {
        NavigationSplitView {
            List(SidebarSection.allCases, selection: $section) { item in
                Label(item.title, systemImage: item.symbol)
                    .tag(item)
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 200, max: 260)
        } detail: {
            NavigationStack(path: $path) {
                detailRoot
                    .navigationDestination(for: Artist.self) { artist in
                        let refreshed = refreshedArtist?.artist.slug == artist.slug
                            ? refreshedArtist
                            : nil
                        ArtistView(
                            artist: refreshed?.artist ?? artist,
                            preparedVM: refreshed?.vm
                                ?? (prepared?.slug == artist.slug ? prepared?.vm : nil)
                        )
                        // Identity changes when Cmd-R lands fresh data, which
                        // is what forces the subtree to rebuild.
                        .id(refreshToken)
                    }
            }
        }
        .frame(minWidth: 900, minHeight: 620)
        .inspector(isPresented: $ui.showQueue) {
            QueueSheet(embedded: true)
                .environment(PlayerViewModel.shared)
                .inspectorColumnWidth(min: 260, ideal: 320, max: 420)
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
            section = .browse
            loader.url = pasted
            Task { await open(pasted) }
        }
        // The stack's root (detailRoot) changes identity with `section`.
        // Switching sections while an Artist is still pushed on top of that
        // root corrupts NavigationStack's internal state and traps on the
        // next push (reproduced: browse → open → switch section → browse →
        // open → EXC_BREAKPOINT in NavigationColumnState.boundPathChange).
        // Clearing the path on every section change keeps root changes and
        // path mutations from ever overlapping.
        .onChange(of: section) { _, _ in
            path = []
        }
        // Nothing is pushed, so neither cache can be reached — and each holds
        // a full Artist plus its view model.
        .onChange(of: path) { _, newPath in
            if newPath.isEmpty {
                refreshedArtist = nil
                prepared = nil
            }
        }
        // ⌘R refreshes the currently pushed artist, if any.
        .onChange(of: ui.refreshToken) { _, _ in
            guard let artist = path.last else { return }
            Task {
                await open(artist.sourceUrl ?? "", artistName: artist.name, forceRefresh: true)
                refreshToken &+= 1
            }
        }
    }

    @ViewBuilder
    private var detailRoot: some View {
        switch section {
        case .browse, nil:
            browsePane
        case .recents:
            ScrollView {
                RecentTrackersListView { entry in
                    Task { await open(entry.sourceUrl) }
                }
                .padding(.vertical, 16)
            }
            .background(Color.lsBackground)
            .navigationTitle("Recents")
        case .favourites:
            FavouritesView(embedded: true)
                .environment(FavouritesManager.shared)
                .environment(vmForCurrentPlayback)
        case .settings:
            // SettingsView already sets its own navigationTitle("Settings")
            // in the embedded path — no need to set it again here.
            SettingsView(embedded: true)
        }
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

            if let error = loader.error {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(Color.lsError)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 8)
            }

            Divider().overlay(Color.lsBorder)

            BrowseArtistsView { pickedUrl, pickedName in
                Task { await open(pickedUrl, artistName: pickedName) }
            }
        }
        .background(Color.lsBackground)
        .navigationTitle("Browse")
    }

    /// Loads a tracker and pushes its screen, building the view model while the
    /// loading state is still up — one loading state per tracker, matching iOS.
    private func open(_ url: String, artistName: String? = nil, forceRefresh: Bool = false) async {
        guard let artist = await loader.load(
            url, artistName: artistName, forceRefresh: forceRefresh, recents: recents
        ) else { return }
        let vm = await loader.preparing { await ArtistViewModel.make(artist: artist) }
        prepared = (artist.slug, vm)
        // Artist: Hashable is slug-only, so re-pushing the same artist is a
        // no-op — the destination is never rebuilt and ArtistView's
        // `.task(id: artist.slug)` doesn't re-fire. Cmd-R therefore refetched,
        // rewrote the cache, and left the screen identical. Bumping this token
        // gives the pushed screen an identity change to react to.
        refreshedArtist = (artist, vm)
        withAnimation { path = [artist] }
    }
}
#endif
