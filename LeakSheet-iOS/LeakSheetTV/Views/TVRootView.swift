import SwiftUI

/// tvOS shell. A sidebar-adaptable TabView is the platform's own top-level
/// navigation — the iOS push-stack-from-a-landing-screen shape doesn't apply
/// when there is no back gesture and the Menu button already pops.
struct TVRootView: View {
    enum Tab: Hashable {
        case browse, recents, favourites, addURL, settings
    }

    @State private var selection: Tab = .browse

    var body: some View {
        TabView(selection: $selection) {
            tab("Browse", "music.note.list", .browse) { TVBrowseView() }
            tab("Recents", "clock", .recents) { TVRecentsView() }
            tab("Favourites", "heart.fill", .favourites) { TVFavouritesView() }
            tab("Add URL", "link", .addURL) { TVURLEntryView() }
            tab("Settings", "gearshape", .settings) { TVSettingsView() }
        }
        .tabViewStyle(.sidebarAdaptable)
        .background(Color.lsBackground)
        .safeAreaBar(edge: .bottom) {
            TVMiniPlayerBar()
        }
    }

    /// Screens own their own NavigationStack (and its path) rather than being
    /// wrapped in one here — they push programmatically after an async load,
    /// so each needs its own binding. The Menu button then pops within the tab
    /// instead of switching tabs.
    private func tab<Content: View>(
        _ title: String,
        _ symbol: String,
        _ value: Tab,
        @ViewBuilder content: @escaping () -> Content
    ) -> some TabContent<Tab> {
        SwiftUI.Tab(title, systemImage: symbol, value: value) {
            content()
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
