#if os(macOS)
import SwiftUI

/// What the detail column is showing. Recents is not a destination on the Mac:
/// opened trackers live in the sidebar itself.
enum MacSelection: Hashable {
    case browse
    case favourites
    case tracker(slug: String)
}

/// A parsed tracker held open across sidebar navigation.
struct LoadedTracker {
    let artist: Artist
    let vm: ArtistViewModel
}

/// Mac window + library state. One main window, so a singleton read by the menu
/// bar, sidebar, detail column and inspector instead of threaded bindings.
@MainActor
@Observable
final class MacUIState {
    static let shared = MacUIState()

    enum InspectorTab: String, CaseIterable, Identifiable {
        case details, queue
        var id: String { rawValue }
        var title: String { self == .details ? "Details" : "Queue" }
    }

    /// Sidebar selection — drives the detail column directly. There is no
    /// navigation stack, so selecting Favourites cannot unload a tracker.
    var selection: MacSelection? = .browse

    /// Trailing inspector rail (Details / Queue).
    var showInspector = false
    var inspectorTab: InspectorTab = .details

    /// The row the song list has selected. Drives the Details tab, so arrowing
    /// through a list updates the panel without opening anything.
    var selectedSong: SongDetailPayload?

    /// Bumped by ⌘R; the detail column re-fetches the selected tracker.
    var refreshToken = 0

    /// Set by ⇧⌘V so the Browse pane can pick up a pasted tracker URL.
    var pastedURL: String?

    /// Bumped by ⌘F. The artist screen owns the search field's focus state, so the
    /// command nudges this and the screen focuses on the change.
    var focusSearchToken = 0

    /// Measured height of the mini player bar: the window-level `safeAreaBar` insets
    /// the detail column but NOT the inspector. Measured, since the bar grows a slider.
    var playerBarHeight: CGFloat = 0

    /// Parsed trackers keyed by slug, most-recently-opened last. Capped: a big tracker
    /// plus its view model is tens of MB.
    private(set) var trackers: [String: LoadedTracker] = [:]
    private var order: [String] = []
    private static let limit = 3

    private init() {}

    var selectedSlug: String? {
        if case .tracker(let slug) = selection { return slug }
        return nil
    }

    func tracker(_ slug: String) -> LoadedTracker? { trackers[slug] }

    /// Mark a tracker as most-recently used (re-selecting never goes through `store`).
    /// Called on selection change, not from `tracker(_:)`, which `body` reads.
    func touch(_ slug: String) {
        guard order.contains(slug), order.last != slug else { return }
        order.removeAll { $0 == slug }
        order.append(slug)
    }

    /// LRU insert. The entry just stored is at the tail, and eviction also skips the
    /// playing tracker, which the mini player and Details panel resolve through this cache.
    func store(_ loaded: LoadedTracker) {
        let slug = loaded.artist.slug
        order.removeAll { $0 == slug }
        order.append(slug)
        trackers[slug] = loaded
        let playing = PlayerViewModel.shared.artistSlug
        while order.count > Self.limit {
            guard let victim = order.first(where: { $0 != playing }) else { break }
            order.removeAll { $0 == victim }
            trackers.removeValue(forKey: victim)
        }
    }

    func forget(slug: String) {
        order.removeAll { $0 == slug }
        trackers.removeValue(forKey: slug)
    }
}
#endif
