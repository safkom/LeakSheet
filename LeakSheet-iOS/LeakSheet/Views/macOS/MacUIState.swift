#if os(macOS)
import SwiftUI

/// What the detail column is showing. Recents is not a destination on the Mac —
/// the trackers you have opened live in the sidebar itself, so going back to one
/// is a click, not a re-load.
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

/// Mac window + library state. One main window (File ▸ New is removed), so a
/// singleton is the whole story: the menu bar, the sidebar, the detail column
/// and the inspector all read the same instance instead of threading bindings.
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

    /// Bumped by ⌘F. The artist screen owns the search field's focus state, so
    /// the menu command cannot set it directly — it nudges this instead and the
    /// screen focuses on the change.
    var focusSearchToken = 0

    /// Measured height of the mini player bar.
    ///
    /// The bar is a window-level `safeAreaBar`, which insets the detail column
    /// but NOT the inspector — so the Details panel's Play button sat behind it
    /// whenever anything was playing. Measured rather than hardcoded because the
    /// bar grows a progress slider once a duration is known.
    var playerBarHeight: CGFloat = 0

    /// Parsed trackers keyed by slug, most-recently-opened last.
    ///
    /// Capped: a big tracker (Ye is ~9k versions) plus its view model is tens of
    /// MB, and holding every tracker a session ever opened would pin all of them.
    private(set) var trackers: [String: LoadedTracker] = [:]
    private var order: [String] = []
    private static let limit = 3

    private init() {}

    var selectedSlug: String? {
        if case .tracker(let slug) = selection { return slug }
        return nil
    }

    func tracker(_ slug: String) -> LoadedTracker? { trackers[slug] }

    /// Mark a tracker as most-recently used.
    ///
    /// Re-selecting an already-loaded tracker never goes through `store`, so its
    /// recency was otherwise frozen at first open and three later trackers could
    /// evict it. Called from the sidebar-selection change rather than from
    /// `tracker(_:)`, which the detail column reads during `body` — bumping
    /// recency there would mutate observed state mid-update.
    func touch(_ slug: String) {
        guard order.contains(slug), order.last != slug else { return }
        order.removeAll { $0 == slug }
        order.append(slug)
    }

    /// LRU insert. The entry just stored is always at the tail, so the eviction
    /// below can never drop what the user is looking at.
    ///
    /// It also skips whatever is currently playing: the mini player and the
    /// Details panel resolve the playing song through this cache
    /// (`vmForCurrentPlayback`), so evicting that tracker left the bar playing a
    /// track it could no longer describe.
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
