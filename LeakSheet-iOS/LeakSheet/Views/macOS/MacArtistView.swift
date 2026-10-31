#if os(macOS)
import SwiftUI

/// The Mac artist screen: a header (art, name, stats, filters), then either the
/// era grid or one era's song list. Forked from `ArtistView` (a grid plus a
/// selectable `List` for clicks, keys and hover) but on the same `ArtistViewModel`.
struct MacArtistView: View {
    let artist: Artist
    @Bindable var vm: ArtistViewModel

    @State var ui = MacUIState.shared
    @State var lastUpdated: Date?
    @State var showStats = false
    @State var showTimeline = false
    @State var showLegend = false
    @State var safariItem: SafariItem?
    @State var embedItem: EmbedItem?

    @Environment(PlayerViewModel.self) var player
    @Environment(\.colorScheme) var colorScheme
    @FocusState var searchFocused: Bool

    /// era name (lowercased) → art URL, first occurrence wins. Precomputed once
    /// so `MiscListView` takes a small dictionary instead of the whole era tree.
    let eraArtByLowercasedName: [String: String?]

    init(artist: Artist, vm: ArtistViewModel) {
        self.artist = artist
        self.vm = vm
        var eraArt: [String: String?] = [:]
        for era in artist.eras where eraArt[era.name.lowercased()] == nil {
            eraArt[era.name.lowercased()] = era.artUrl
        }
        self.eraArtByLowercasedName = eraArt
    }

    /// The era drilled into, or nil for the grid; search, badge filters and content
    /// tabs force the flat list. Reads the view model's `expandedEra` directly: a second
    /// copy desyncs when turning off a badge filter clears it.
    var openEra: String? {
        isFlatMode ? nil : vm.expandedEra
    }

    /// True when the filter state produces one cross-era song list; see
    /// DECISIONS.md::MacArtistView.swift::flat-modes.
    var isFlatMode: Bool {
        vm.isSearching || vm.isBadgeFilterActive || vm.recents || isMiscMode
    }

    /// Content tabs carry `MiscEntry` values, not songs, so they render through the
    /// shared accordion.
    ///
    /// ponytail: reuses iOS `MiscListView` verbatim (no selection, keys or hover); fork it if tabs get browsed heavily.
    var isMiscMode: Bool {
        vm.selectedTabKey != nil
    }

    var hasTimeline: Bool {
        artist.eras.contains { !($0.timeline ?? []).isEmpty }
    }

    var body: some View {
        // Computed ONCE per body evaluation and handed down to every use site.
        let rows = visibleRows
        content(rows)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Color.lsBackground)
        .navigationTitle(openEra ?? artist.name)
        .navigationSubtitle(subtitleText)
        .searchable(text: $vm.searchQuery, prompt: "Search songs…")
        .searchFocused($searchFocused)
        // ⌘F focuses the search field; the command bumps a token because focus state
        // belongs to this view.
        .onChange(of: ui.focusSearchToken) { _, _ in searchFocused = true }
        .toolbar { toolbarItems }
        // Esc leaves an open era, as ⌘[ does.
        .onExitCommand {
            guard openEra != nil else { return }
            vm.openEra(nil)
            ui.selectedSong = nil
        }
        .sheet(isPresented: $showStats) {
            if let trackerStats = artist.trackerStats { TrackerStatsSheet(stats: trackerStats, artist: artist) }
        }
        .sheet(isPresented: $showTimeline) { TrackerTimelineSheet(artist: artist) }
        .sheet(isPresented: $showLegend) { BadgeLegendSheet() }
        .webSheet(item: $safariItem)
        .sheet(item: $embedItem) { EmbedPlayerView(item: $0) }
        // Era card gradients and header contrast are derived per appearance.
        .onChange(of: colorScheme, initial: true) { _, scheme in
            vm.setColorScheme(scheme)
        }
        // Keyed on the view model's identity, not the slug: ⌘R replaces the parsed
        // tracker in place under the same slug.
        .onChange(of: vm.eraPlaybackRevision) {
            player.setArtistEras(vm.eraPlaybackContexts)
        }
        .task(id: ObjectIdentifier(vm)) {
            if let url = artist.sourceUrl {
                lastUpdated = await CacheService.shared.getCachedMeta(for: url)?.timestamp
            }
            player.setArtistEras(vm.eraPlaybackContexts)
            await vm.warmEraArt()
        }
    }

    private var subtitleText: String {
        if let openEra, let era = vm.filteredEra(named: openEra) {
            let n = era.allSongs.count
            return "\(n.formatted()) song\(n == 1 ? "" : "s") · \(artist.name)"
        }
        return "\(vm.artistStats.total.formatted()) tracks"
    }

}

/// Filter chip at Mac control height. The iOS chip carries a 44pt minimum and
/// full glass; here it reads as a toggle in a control strip.
struct MacFilterChip: View {
    let label: String
    let icon: String
    let isActive: Bool
    var tint: Color = .lsAccent
    var onTap: () -> Void

    /// `tint` is a `Color.tone`, whose light variant is darker than its dark one, so the
    /// label is judged in the actual scheme: DECISIONS.md::DesignTokens.swift::scheme-parameter.
    @Environment(\.colorScheme) var colorScheme

    var body: some View {
        Button(action: onTap) {
            Label(label, systemImage: icon)
                .font(.caption.weight(.medium))
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .frame(minHeight: Metrics.chipHeight)
                .foregroundStyle(isActive ? Color.preferredText(on: tint, in: colorScheme) : Color.secondary)
                .background(isActive ? tint : Color.lsCard, in: Capsule())
                .overlay { Capsule().stroke(Color.lsBorder, lineWidth: isActive ? 0 : 1) }
        }
        .buttonStyle(.plain)
        .contentShape(Capsule())
        .accessibilityAddTraits(isActive ? [.isSelected] : [])
    }
}
#endif
