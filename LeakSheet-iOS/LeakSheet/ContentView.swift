import SwiftUI

struct ContentView: View {
    @State private var path: [Artist] = []
    @State private var showFavourites = false
    @State private var showSettings = false
    @State private var showBrowse = false
    @State private var pendingBrowse: PendingBrowse?

    var body: some View {
        NavigationStack(path: $path) {
            LandingView(
                onArtistLoaded: { artist in
                    withAnimation { path.append(artist) }
                },
                onBrowseTapped: { showBrowse = true },
                pendingBrowse: $pendingBrowse
            )
            .navigationDestination(for: Artist.self) { artist in
                ArtistView(artist: artist)
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
        // safeAreaBar (not overlay) registers the mini player as a bottom
        // bar, so the system stacks the floating search field above it
        // instead of laying it out underneath, and scroll content is
        // automatically inset to clear the bar.
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
