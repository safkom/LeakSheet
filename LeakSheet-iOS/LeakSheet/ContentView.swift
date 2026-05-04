import SwiftUI

struct ContentView: View {
    @State private var path: [Artist] = []
    @State private var showFavourites = false
    @State private var showSettings = false
    @State private var showBrowse = false
    @State private var pendingBrowseUrl: String?

    var body: some View {
        NavigationStack(path: $path) {
            LandingView(
                onArtistLoaded: { artist in
                    withAnimation { path.append(artist) }
                },
                onBrowseTapped: { showBrowse = true },
                pendingBrowseUrl: $pendingBrowseUrl
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
        .overlay(alignment: .bottom) {
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
            BrowseArtistsView { pickedUrl in
                showBrowse = false
                pendingBrowseUrl = pickedUrl
            }
        }
    }
}
