import SwiftUI

struct ContentView: View {
    @State private var path: [Artist] = []
    @State private var showFavourites = false
    @State private var showSettings = false
    @State private var showBrowse = false
    @State private var pendingBrowse: PendingBrowse?
    /// View model built while the landing screen still shows its loading
    /// state, handed to the pushed screen so the app has ONE loading state
    /// per tracker instead of "Loading…" followed by "Preparing…".
    @State private var prepared: (slug: String, vm: ArtistViewModel)?

    var body: some View {
        NavigationStack(path: $path) {
            LandingView(
                onArtistLoaded: { artist in
                    // Still inside the landing spinner: build the view model
                    // (off-main filter/stats pass) before navigating.
                    let vm = await ArtistViewModel.make(artist: artist)
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
                ToolbarItemGroup(placement: .topBarTrailing) {
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
        .environment(PlayerViewModel.shared)
        .environment(FavouritesManager.shared)
        .environment(RecentTrackersManager.shared)
        // safeAreaBar not overlay — see DECISIONS.md::ContentView.swift::safeAreaBar
        .safeAreaBar(edge: .bottom) {
            MiniPlayerBar()
                .environment(PlayerViewModel.shared)
        }
        .sheet(isPresented: $showFavourites) {
            FavouritesView()
                .environment(FavouritesManager.shared)
                .environment(PlayerViewModel.shared)
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
        }
        .sheet(isPresented: $showBrowse) {
            BrowseArtistsView { pickedUrl, pickedName in
                showBrowse = false
                pendingBrowse = PendingBrowse(url: pickedUrl, name: pickedName)
            }
        }
    }
}
