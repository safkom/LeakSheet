import Foundation

/// The pure, off-main half of the artist screen's filter pipeline: `nonisolated
/// static` functions over an `Artist` and a `FilterState`, touching no instance
/// state. An extension, so call sites keep using `ArtistViewModel.computeContent(...)`.
extension ArtistViewModel {
    // MARK: - Content computation (pure, runs off-main)

    nonisolated static func computeContent(
        artist: Artist,
        state: FilterState,
        eraStats: [String: Stats],
        searchIndex: [[SongSearchFields]] = []
    ) -> FilteredContent {
        let empty = FilteredContent(
            state: state, eras: [], searchResults: [], recentResults: [],
            recentPlaybackItems: [], recentStreamIndex: [:], miscResults: []
        )

        if let tabKey = state.tabKey {
            let miscResults = computeMiscResults(artist: artist, tabKey: tabKey, state: state)
            return FilteredContent(
                state: state, eras: [], searchResults: [], recentResults: [],
                recentPlaybackItems: [], recentStreamIndex: [:],
                miscResults: miscResults,
                miscEraGroups: groupMiscByEra(miscResults, eraOrder: artist.eras.map(\.name))
            )
        }

        if !state.query.isEmpty {
            return FilteredContent(
                state: state, eras: [],
                searchResults: computeSearchResults(artist: artist, state: state, searchIndex: searchIndex),
                recentResults: [], recentPlaybackItems: [], recentStreamIndex: [:],
                miscResults: []
            )
        }

        if state.recents {
            return recentContent(artist: artist, state: state)
        }
        guard let eras = filteredEras(artist: artist, state: state, eraStats: eraStats) else { return empty }
        return FilteredContent(
            state: state, eras: eras, searchResults: [], recentResults: [],
            recentPlaybackItems: [], recentStreamIndex: [:], miscResults: []
        )
    }

    private nonisolated static func recentContent(artist: Artist, state: FilterState) -> FilteredContent {
        let results = computeRecentResults(artist: artist, state: state)
        var playbackItems: [PlaybackListItem] = []
        var streamIndex: [String: Int] = [:]
        for result in results where result.version.isStreamable {
            streamIndex[result.id] = playbackItems.count
            playbackItems.append(PlaybackListItem(
                version: result.version,
                artistName: artist.name,
                eraName: result.era.name,
                artUrl: result.era.artUrl ?? "",
                artistSlug: artist.slug
            ))
        }
        return FilteredContent(
            state: state, eras: [], searchResults: [],
            recentResults: results,
            recentPlaybackItems: playbackItems,
            recentStreamIndex: streamIndex,
            miscResults: []
        )
    }

    /// The eras with songs left after the filters, or nil when the task was cancelled.
    private nonisolated static func filteredEras(
        artist: Artist, state: FilterState, eraStats: [String: Stats]
    ) -> [FilteredEra]? {
        var eras: [FilteredEra] = []
        eras.reserveCapacity(artist.eras.count)
        for era in artist.eras {
            if Task.isCancelled { return nil }
            let allSongs = era.allSongs
            guard !allSongs.isEmpty, allSongs.contains(where: { songPassesBadgeFilters(
                $0,
                state: state
            ) }) else { continue }
            let sections = (era.sections ?? []).compactMap { section -> Section? in
                let songs = filterSongs(section.songs, state: state)
                guard !songs.isEmpty else { return nil }
                return Section(name: section.name, group: section.group, songs: songs, notes: section.notes)
            }
            // Songs only live in sections, so this is the same list the
            // sections were just filtered into — not a second filter pass.
            let songs = sections.flatMap(\.songs)
            guard !songs.isEmpty else { continue }
            eras.append(FilteredEra(
                era: era,
                sections: sections,
                songs: songs,
                stats: eraStats[era.name] ?? Stats(total: 0, available: 0, snippets: 0, confirmed: 0, fullHQ: 0)
            ))
        }
        return eras
    }

    /// Each active badge filter needs at least one version carrying that badge.
    private nonisolated static func songPassesBadgeFilters(_ song: Song, state: FilterState) -> Bool {
        (!state.bestOf || song.versions.contains(where: isBestOfVersion))
            && (!state.worstOf || song.versions.contains(where: isWorstOfVersion))
            && (!state.grails || song.versions.contains(where: isGrailOrWantedVersion))
    }

    private nonisolated static func versionPassesFilters(_ version: SongVersion, state: FilterState) -> Bool {
        (!state.bestOf || isBestOfVersion(version))
            && (!state.worstOf || isWorstOfVersion(version))
            && (!state.grails || isGrailOrWantedVersion(version))
            && !(state.noSnippets && shouldFilterForNoSnippets(version))
    }

    private nonisolated static func filterSongs(_ songs: [Song], state: FilterState) -> [Song] {
        guard state.bestOf || state.worstOf || state.grails || state.noSnippets else { return songs }
        return songs.compactMap { song in
            song.withFilteredVersions { version in
                versionPassesFilters(version, state: state)
            }
        }
    }

    // MARK: - Flat search results (ranked)

    nonisolated struct SearchResult: Identifiable, Hashable, Sendable {
        let song: Song
        let version: SongVersion
        let era: Era
        let score: Int
        /// Position of the song within its era's flattened list: disambiguates
        /// same-`baseName` songs ("???" placeholders), as EraRow's ordinal does.
        let songOrdinal: Int

        // Stable content-derived id — see DECISIONS.md::FilterPipeline.swift::stable-row-id
        var id: String { "\(era.name)::\(songOrdinal)::\(song.baseName)::\(version.id)" }
    }

    /// Upper bound on search rows handed to the list. Highest-scoring first,
    /// so the cut only ever drops weak matches.
    nonisolated static let maxSearchResults = 500

    private nonisolated static func computeSearchResults(
        artist: Artist, state: FilterState, searchIndex: [[SongSearchFields]]
    ) -> [SearchResult] {
        // Punctuation-insensitive, like the fields it is compared with:
        // "stay on em" finds "Stay On 'Em".
        guard !state.query.isEmpty else { return [] }
        let needle = Song.nameKey(state.query)
        // Use the prebuilt haystack when its shape matches; otherwise fall back
        // to inline scoring so correctness never depends on the index.
        let useIndex = searchIndex.count == artist.eras.count
        var results: [SearchResult] = []
        for (eraIdx, era) in artist.eras.enumerated() {
            if Task.isCancelled { return [] }
            let songs = era.allSongs
            let eraFields = (useIndex && searchIndex[eraIdx].count == songs.count) ? searchIndex[eraIdx] : nil
            for (songIdx, song) in songs.enumerated() {
                let score = eraFields.map { scoreSong(fields: $0[songIdx], query: needle) }
                    ?? scoreSong(song, query: needle)
                guard score > 0 else { continue }
                for version in song.versions {
                    if state.bestOf && !isBestOfVersion(version) { continue }
                    if state.worstOf && !isWorstOfVersion(version) { continue }
                    if state.grails && !isGrailOrWantedVersion(version) { continue }
                    if state.noSnippets && shouldFilterForNoSnippets(version) { continue }
                    results.append(SearchResult(
                        song: song,
                        version: version,
                        era: era,
                        score: score,
                        songOrdinal: songIdx
                    ))
                }
            }
        }
        results.sort { $0.score > $1.score }
        // Capped: a 1-2 character query on a large tracker matches tens of thousands of
        // versions, and the sort above keeps the best ones.
        return Array(results.prefix(Self.maxSearchResults))
    }

    // MARK: - Recents

    nonisolated struct RecentResult: Identifiable, Equatable, Sendable {
        let song: Song
        let version: SongVersion
        let era: Era
        let timestamp: TimeInterval
        /// Position of the song within its era's flattened list; disambiguates
        /// same-`baseName` songs. See SearchResult.
        let songOrdinal: Int

        // Stable content-derived id — see DECISIONS.md::FilterPipeline.swift::stable-row-id
        var id: String { "\(era.name)::\(songOrdinal)::\(song.baseName)::\(version.id)" }
    }

    nonisolated static func computeRecentResults(artist: Artist, state: FilterState) -> [RecentResult] {
        var results: [RecentResult] = []
        for era in artist.eras {
            if Task.isCancelled { return [] }
            for (songOrdinal, song) in era.allSongs.enumerated() where songPassesBadgeFilters(song, state: state) {
                for version in song.versions where versionPassesFilters(version, state: state) {
                    // previewDate last: a leak/file date is the real event, but a preview-only
                    // version has nothing else.
                    let dateStr = [version.leakDate, version.fileDate, version.previewDate]
                        .compactMap { $0 }
                        .first { !$0.isEmpty }
                    guard let dateStr else { continue }
                    // Recents play the link that leaked on this date, not the row's oldest.
                    results.append(RecentResult(
                        song: song, version: version.playing(version.recentLeakLink), era: era,
                        timestamp: parseLeakDate(dateStr), songOrdinal: songOrdinal
                    ))
                }
            }
        }
        results.sort { $0.timestamp > $1.timestamp }
        return results
    }

    // MARK: - Misc entries

    /// Group a content tab's entries by era, in the artist's own era order
    /// (`eraOrder`), so a tab reads in the same sequence as the Unreleased list.
    /// Groups matching no era keep their relative order and go last.
    nonisolated static func groupMiscByEra(
        _ entries: [MiscEntry], eraOrder: [String] = []
    ) -> [MiscEraGroup] {
        var order: [String] = []
        var byEra: [String: [MiscEntry]] = [:]
        for entry in entries {
            if byEra[entry.eraName] == nil { order.append(entry.eraName) }
            byEra[entry.eraName, default: []].append(entry)
        }
        guard !eraOrder.isEmpty else {
            return order.map { MiscEraGroup(eraName: $0, entries: byEra[$0] ?? []) }
        }
        // Case/whitespace-insensitive: a tab's Era column is typed by hand and
        // does not always match the era header's capitalisation exactly.
        var rank: [String: Int] = [:]
        for (index, name) in eraOrder.enumerated() {
            rank[Self.eraMatchKey(name)] = index
        }
        let sorted = order.enumerated().sorted { lhs, rhs in
            let lhsRank = rank[Self.eraMatchKey(lhs.element)]
            let rhsRank = rank[Self.eraMatchKey(rhs.element)]
            switch (lhsRank, rhsRank) {
            case let (lhsRank?, rhsRank?): return lhsRank == rhsRank ? lhs.offset < rhs.offset : lhsRank < rhsRank
            case (nil, nil):   return lhs.offset < rhs.offset
            case (nil, _):     return false   // unmatched sorts after matched
            case (_, nil):     return true
            }
        }
        return sorted.map { MiscEraGroup(eraName: $0.element, entries: byEra[$0.element] ?? []) }
    }

    /// Loose era identity for matching a content tab's Era column against the
    /// era tree. Deliberately not the backend's `_era_match_key` — this only
    /// needs to survive casing and stray whitespace.
    nonisolated static func eraMatchKey(_ name: String) -> String {
        name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    /// Misc entries after in-mode filters: No Snippets drops unavailable
    /// entries, Recent sorts by date descending, search matches name /
    /// notes / era / type. Best Of, Worst Of and Grails keep only their badge-marked
    /// names, so a tab with none shows empty rather than the whole tab.
    private nonisolated static func computeMiscResults(
        artist: Artist,
        tabKey: String,
        state: FilterState
    ) -> [MiscEntry] {
        var entries = artist.tabs?.first(where: { $0.id == tabKey })?.entries ?? []
        if state.noSnippets {
            entries = entries.filter { !isSnippetLike(available: $0.available, quality: $0.quality) }
        }
        if state.bestOf {
            // Match only best/special emojis, the same set as isBestOfVersion (not 🗑️ or 🤖).
            entries = entries.filter { entry in
                Badge.allCases.contains { $0.isBestOf && entry.name.contains($0.emoji) }
            }
        }
        if state.worstOf {
            entries = entries.filter { $0.name.contains(Badge.worst.emoji) }
        }
        if state.grails {
            // Grail + wanted, matching the eras branch's combined chip.
            entries = entries.filter { entry in
                entry.name.contains(Badge.grail.emoji) || entry.name.contains(Badge.wanted.emoji)
            }
        }
        if !state.query.isEmpty {
            let query = state.query
            entries = entries.filter { entry in
                entry.name.lowercased().contains(query)
                    || (entry.notes ?? "").lowercased().contains(query)
                    || entry.eraName.lowercased().contains(query)
                    || (entry.entryType ?? "").lowercased().contains(query)
            }
        }
        if state.recents {
            // Parse each date once: inside the comparator it ran ~n log n
            // times, each trying several DateFormatters.
            let dates = entries.map { Self.parseLeakDate($0.date ?? "") }
            entries = entries.indices.sorted { dates[$0] > dates[$1] }.map { entries[$0] }
        }
        return entries
    }

}
