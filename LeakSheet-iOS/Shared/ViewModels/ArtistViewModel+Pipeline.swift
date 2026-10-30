import Foundation
import SwiftUI
import Observation

extension ArtistViewModel {
    // MARK: - Factory

    /// How many era covers are warmed before the artist screen is pushed: about two
    /// screenfuls of collapsed cards, without a 40-era tracker waiting on 40 downloads.
    static let coldStartArtCount = 8

    /// Preferred construction path: the stats/content pass runs off-main.
    ///
    /// Also pulls the first few era covers (and their colours) into the cache while the
    /// landing spinner still shows, so the first cards don't pop in grey.
    static func make(artist: Artist) async -> ArtistViewModel {
        let precomputed = await Task.detached(priority: .userInitiated) {
            Precomputed(artist: artist)
        }.value
        let vm = ArtistViewModel(artist: artist, precomputed: precomputed)
        await vm.warmEraArt(limit: coldStartArtCount)
        return vm
    }

    /// Load era covers into the image cache and derive their display colours (bytes
    /// alone would still leave cards grey for a frame).
    ///
    /// `limit` nil warms every era (the background pass from ArtistView).
    func warmEraArt(limit: Int? = nil) async {
        let eras = limit.map { Array(artist.eras.prefix($0)) } ?? artist.eras
        // Keyed on the cover, not the era: sibling eras can share one, and the result
        // is applied to every era using that URL below.
        var seenArt = Set<String>()
        let targets: [(artUrl: String, url: URL)] = eras.compactMap { era in
            guard let art = era.artUrl,
                  eraDisplay[era.name] == nil,
                  seenArt.insert(art).inserted,
                  let url = APIClient.shared.imageProxyURL(for: art, width: 320)
            else { return nil }
            return (art, url)
        }
        guard !targets.isEmpty else { return }

        await withTaskGroup(of: (String, Color)?.self) { group in
            // Enough to saturate the link without starving the cover the user
            // is looking at.
            let slots = 4
            var next = 0
            var inFlight = 0
            func addTask() {
                let target = targets[next]
                next += 1
                inFlight += 1
                group.addTask {
                    guard let image = await ImageCache.shared.loadImage(
                        from: target.url, maxPixelSize: 320
                    ) else { return nil }
                    guard let color = await EraColorExtractor.shared.extractColor(
                        fromImage: image, cacheKey: target.artUrl
                    ) else { return nil }
                    return (target.artUrl, color)
                }
            }
            while next < targets.count && inFlight < slots { addTask() }
            while inFlight > 0 {
                let result = await group.next() ?? nil
                inFlight -= 1
                if let (artUrl, color) = result {
                    for era in eras where era.artUrl == artUrl {
                        setEraColor(eraName: era.name, dominant: color)
                    }
                }
                if Task.isCancelled { break }
                if next < targets.count { addTask() }
            }
            group.cancelAll()
        }
    }

    // MARK: - Era colors

    /// Re-derive every cached era colour for a new appearance. No-op when the
    /// scheme is unchanged, so it is safe to call from `onChange`. The raw
    /// dominant colours are appearance-independent, so nothing is re-extracted.
    func setColorScheme(_ scheme: ColorScheme) {
        guard scheme != colorScheme else { return }
        colorScheme = scheme
        eraDisplay = eraDisplay.mapValues { EraDisplayColors.derive(from: $0.dominant, in: scheme) }
    }

    /// Idempotent — extraction is deterministic and cached, so the first
    /// derivation per era wins and later callbacks are no-ops. Buffers into
    /// `pendingEraColors` and coalesces same-turn callbacks into a single
    /// `eraDisplay` write on the next runloop tick.
    func setEraColor(eraName: String, dominant: Color) {
        guard eraDisplay[eraName] == nil, pendingEraColors[eraName] == nil else { return }
        pendingEraColors[eraName] = EraDisplayColors.derive(from: dominant, in: colorScheme)
        scheduleEraColorFlush()
    }

    private func scheduleEraColorFlush() {
        guard !eraColorFlushScheduled else { return }
        eraColorFlushScheduled = true
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.eraColorFlushScheduled = false
            guard !self.pendingEraColors.isEmpty else { return }
            var merged = self.eraDisplay
            for (name, colors) in self.pendingEraColors { merged[name] = colors }
            self.eraDisplay = merged
            self.pendingEraColors.removeAll()
        }
    }

    // MARK: - Debounce

    func scheduleDebounce() {
        debounceTask?.cancel()
        let q = searchQuery.trimmingCharacters(in: .whitespaces)
        if q.isEmpty {
            debouncedQuery = ""
            applyFilters()
            return
        }
        // Honest filtering indicator — see DECISIONS.md::ArtistViewModel.swift::filtering-indicator
        if q != debouncedQuery {
            isFiltering = true
        }
        debounceTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled else { return }
            self?.debouncedQuery = q
            self?.applyFilters()
        }
    }

    // MARK: - Filter pipeline

    private var currentFilterState: FilterState {
        FilterState(
            query: debouncedQuery.lowercased(),
            bestOf: bestOf,
            worstOf: worstOf,
            grails: grails,
            recents: recents,
            noSnippets: noSnippets,
            tabKey: selectedTabKey
        )
    }

    func applyFilters() {
        let previousTask = filterTask
        previousTask?.cancel()
        let state = currentFilterState
        guard state != content.state else {
            isFiltering = false
            return
        }
        isFiltering = true
        let artist = self.artist
        let eraStats = self.eraStatsByName
        let searchIndex = self.searchIndex
        // Single-flight filtering — see DECISIONS.md::ArtistViewModel.swift::single-flight-filter
        filterTask = Task.detached(priority: .userInitiated) { [weak self] in
            await previousTask?.value
            guard !Task.isCancelled else { return }
            let result = ArtistViewModel.computeContent(
                artist: artist,
                state: state,
                eraStats: eraStats,
                searchIndex: searchIndex
            )
            let contexts = ArtistViewModel.filteredEraContexts(artist: artist, state: state, result: result)
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                // Stale guard — a newer toggle may have superseded this
                // compute even if cancellation missed it.
                guard self.currentFilterState == state else { return }
                self.content = result
                self.isFiltering = false
                // Re-register only when the list actually changes: a registration resets the
                // playing era's position, and search keystrokes would otherwise do it per key.
                if contexts != nil || self.eraPlaybackIsFiltered {
                    self.eraPlaybackContexts = contexts ?? self.allEraPlaybackContexts
                    self.eraPlaybackIsFiltered = contexts != nil
                    self.eraPlaybackRevision += 1
                }
                // Ordinals are positions within the FILTERED era, so a filter change renumbers
                // them and the expanded set must reset.
                self.expandedSongs.removeAll()
                self.resetRecentsWindow()
                self.rebuildEraRows()
            }
        }
    }

    /// Rollover order while the eras view shows filter chips: every era stays registered, a
    /// filtered-out one with no versions, so the playing era is still found and empty ones are
    /// skipped. Nil elsewhere (no chips, search, recents, tabs): the whole tracker.
    nonisolated static func filteredEraContexts(
        artist: Artist, state: FilterState, result: FilteredContent
    ) -> [EraSongContext]? {
        let erasView = state.query.isEmpty && !state.recents && state.tabKey == nil
        guard erasView, state != FilterState() else { return nil }
        var kept = result.eras[...]
        return artist.eras.map { era in
            var versions: [SongVersion] = []
            if let first = kept.first, first.era.name == era.name {
                versions = first.streamableVersions
                kept = kept.dropFirst()
            }
            return EraSongContext(
                eraName: era.name, artistName: artist.name, artUrl: era.artUrl ?? "",
                versions: versions, artistSlug: artist.slug
            )
        }
    }

    // MARK: - Recents paging

    private func resetRecentsWindow() {
        visibleRecents = Array(content.recentResults.prefix(Self.recentsPageSize))
    }

    var hasMoreRecents: Bool {
        visibleRecents.count < content.recentResults.count
    }

    func loadMoreRecents() {
        guard hasMoreRecents else { return }
        let next = min(visibleRecents.count + Self.recentsPageSize, content.recentResults.count)
        visibleRecents = Array(content.recentResults.prefix(next))
    }

    /// Playback list + start index for a tapped recents row.
    func recentPlayback(for resultId: String) -> (items: [PlaybackListItem], startAt: Int)? {
        guard let idx = content.recentStreamIndex[resultId] else { return nil }
        return (content.recentPlaybackItems, idx)
    }
}
