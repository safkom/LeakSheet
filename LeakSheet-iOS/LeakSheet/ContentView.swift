import SwiftUI

struct ContentView: View {
    @State private var path: [Artist] = []
    @State private var showFavourites = false
    @State private var showSettings = false
    @State private var showBrowse = false
    @State private var pendingBrowse: PendingBrowse?
    @Environment(\.colorScheme) private var colorScheme
    /// View model built while the landing screen still shows its loading
    /// state, handed to the pushed screen so the app has ONE loading state
    /// per tracker instead of "Loading…" followed by "Preparing…".
    @State private var prepared: (slug: String, vm: ArtistViewModel)?
    /// See DECISIONS.md::ContentView.swift::mini-player-inset.
    @State private var miniPlayerHeight: CGFloat = 0

    /// The prepared view model, only when it describes the artist actually playing.
    /// Reads the singleton, not @Environment: this view installs PlayerViewModel itself.
    private var vmForCurrentPlayback: ArtistViewModel? {
        guard let prepared, prepared.slug == PlayerViewModel.shared.artistSlug else { return nil }
        return prepared.vm
    }

    private func consumeDeepLink() {
        guard let pending = DeepLinkRouter.shared.pending else { return }
        DeepLinkRouter.shared.pending = nil
        pendingBrowse = pending
    }

    var body: some View {
        NavigationStack(path: $path) {
            LandingView(
                onArtistLoaded: { artist, notice in
                    // Still inside the landing spinner: build the view model
                    // (off-main filter/stats pass) before navigating.
                    let vm = await ArtistViewModel.make(artist: artist)
                    vm.loadNotice = notice
                    prepared = (artist.slug, vm)
                    withAnimation { path.append(artist) }
                },
                onBrowseTapped: { showBrowse = true },
                pendingBrowse: $pendingBrowse
            )
            .navigationDestination(for: Artist.self) { artist in
                ArtistView(
                    artist: artist,
                    preparedVM: prepared?.slug == artist.slug ? prepared?.vm : nil
                )
            }
            .toolbar {
                ToolbarItemGroup(placement: .primaryAction) {
                    Button {
                        showFavourites = true
                    } label: {
                        Image(systemName: "heart.fill")
                    }
                    .accessibilityLabel("Favourites")
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("Settings")
                }
            }
        }
        // Zero without a track: the empty bar never re-measures, so its last height goes stale.
        .environment(\.miniPlayerInset, PlayerViewModel.shared.currentTrack == nil ? 0 : miniPlayerHeight)
        .environment(PlayerViewModel.shared)
        .environment(FavouritesManager.shared)
        .environment(RecentTrackersManager.shared)
        // safeAreaBar not overlay — see DECISIONS.md::ContentView.swift::safeAreaBar
        .safeAreaBar(edge: .bottom) {
            MiniPlayerBar()
                .environment(PlayerViewModel.shared)
                .environment(vmForCurrentPlayback)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { miniPlayerHeight = $0 }
        }
        .sheet(isPresented: $showFavourites) {
            FavouritesView()
                .environment(FavouritesManager.shared)
                .environment(PlayerViewModel.shared)
                .environment(vmForCurrentPlayback)
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(presenterScheme: colorScheme)
        }
        // A Siri/Shortcuts/Spotlight open: consumed on change and on first appearance, since an
        // intent can set it before this view exists.
        .onChange(of: DeepLinkRouter.shared.pending) { _, _ in consumeDeepLink() }
        .onAppear { consumeDeepLink() }
        .sheet(isPresented: $showBrowse) {
            BrowseArtistsView { pickedUrl, pickedName in
                showBrowse = false
                pendingBrowse = PendingBrowse(url: pickedUrl, name: pickedName)
            }
        }
    }
}

extension EnvironmentValues {
    /// Height of the floating mini player, for scroll views that must clear it themselves.
    @Entry var miniPlayerInset: CGFloat = 0
}
