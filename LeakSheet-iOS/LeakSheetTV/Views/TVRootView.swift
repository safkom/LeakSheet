import SwiftUI

/// tvOS shell. A sidebar-adaptable TabView is the platform's own top-level
/// navigation — the iOS push-stack-from-a-landing-screen shape doesn't apply
/// when there is no back gesture and the Menu button already pops.
struct TVRootView: View {
    enum Tab: Hashable {
        case browse, recents, favourites, addURL, settings
    }

    @State private var selection: Tab = .browse

    // Each screen owns its own NavigationStack (and its path) rather than
    // being wrapped in one here — they push programmatically after an async
    // load, so each needs its own binding. The Menu button then pops within
    // the tab instead of switching tabs.
    var body: some View {
        TabView(selection: $selection) {
            // Qualified as SwiftUI.Tab: the nested `Tab` enum above shadows it.
            SwiftUI.Tab("Browse", systemImage: "music.note.list", value: Tab.browse) { TVBrowseView() }
            SwiftUI.Tab("Recents", systemImage: "clock", value: Tab.recents) { TVRecentsView() }
            SwiftUI.Tab("Favourites", systemImage: "heart.fill", value: Tab.favourites) { TVFavouritesView() }
            SwiftUI.Tab("Add URL", systemImage: "link", value: Tab.addURL) { TVURLEntryView() }
            SwiftUI.Tab("Settings", systemImage: "gearshape", value: Tab.settings) { TVSettingsView() }
        }
        .tabViewStyle(.sidebarAdaptable)
        .background(Color.lsBackground)
        .safeAreaBar(edge: .bottom) {
            TVMiniPlayerBar()
        }
    }
}

/// The tvOS navigation graph. Value-typed so any screen can push without
/// threading bindings through, mirroring iOS's `navigationDestination(for:)`.
enum TVRoute: Hashable {
    case artist(Artist)
    case song(SongDetailPayload)

    @MainActor
    @ViewBuilder
    var destination: some View {
        switch self {
        case .artist(let artist):
            TVArtistView(artist: artist)
        case .song(let payload):
            TVSongDetailView(payload: payload)
        }
    }
}
