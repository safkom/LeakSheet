import Foundation

/// The pure, off-main half of the artist screen's filter pipeline.
///
/// Split out of `ArtistViewModel` (2026-07-25): the view model is the
/// MainActor-isolated state holder, while everything here is `nonisolated
/// static` — it takes an `Artist` plus a `FilterState` and returns computed
/// values, touching no instance state. Keeping it in its own file makes that
/// boundary obvious and keeps the view model readable.
///
/// Declared as an extension so every call site and test keeps using
/// `ArtistViewModel.computeContent(...)` / `.parseLeakDate(...)` unchanged.
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

        if state.misc || state.tabKey != nil {
            let miscResults = computeMiscResults(artist: artist, state: state)
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

        // Eras branch
        var eras: [FilteredEra] = []
        eras.reserveCapacity(artist.eras.count)
        for era in artist.eras {
            if Task.isCancelled { return empty }
            let allSongs = era.allSongs
            guard !allSongs.isEmpty else { continue }

            if state.bestOf {
                let hasBest = allSongs.contains { song in
                    song.versions.contains { isBestOfVersion($0) }
                }
                guard hasBest else { continue }
            }
            if state.worstOf {
                let hasWorst = allSongs.contains { song in
                    song.versions.contains { isWorstOfVersion($0) }
                }
                guard hasWorst else { continue }
            }
            if state.grails {
                let hasGrail = allSongs.contains { song in
                    song.versions.contains { isGrailOrWantedVersion($0) }
                }
                guard hasGrail else { continue }
            }

            let sections = (era.sections ?? []).compactMap { section -> Section? in
                let songs = filterSongs(section.songs, state: state)
                guard !songs.isEmpty else { return nil }
                return Section(name: section.name, group: section.group, songs: songs)
            }
            let songs = filterSongs(allSongs, state: state)
            guard !songs.isEmpty else { continue }

            eras.append(FilteredEra(
                era: era,
                sections: sections,
                songs: songs,
                stats: eraStats[era.name] ?? Stats(total: 0, available: 0, snippets: 0, confirmed: 0, fullHQ: 0)
            ))
        }
        return FilteredContent(
            state: state, eras: eras, searchResults: [], recentResults: [],
            recentPlaybackItems: [], recentStreamIndex: [:], miscResults: []
        )
    }

    private nonisolated static func filterSongs(_ songs: [Song], state: FilterState) -> [Song] {
        guard state.bestOf || state.worstOf || state.grails || state.noSnippets else { return songs }
        return songs.compactMap { song in
            song.withFilteredVersions { version in
                if state.bestOf && !isBestOfVersion(version) { return false }
                if state.worstOf && !isWorstOfVersion(version) { return false }
                if state.grails && !isGrailOrWantedVersion(version) { return false }
                if state.noSnippets && shouldFilterForNoSnippets(version) { return false }
                return true
            }
        }
    }

    // MARK: - Flat search results (ranked)

    nonisolated struct SearchResult: Identifiable, Hashable, Sendable {
        let song: Song
        let version: SongVersion
        let era: Era
        let score: Int
        /// Position of the song within its era's flattened list. Disambiguates
        /// same-`baseName` songs (leak trackers emit several distinct "???"
        /// placeholders per era with an identical single version) whose ids
        /// would otherwise collide and be silently dropped by ForEach — the
        /// same fix EraRow.id applies with its ordinal.
        let songOrdinal: Int

        // Stable id derived from content so SwiftUI's ForEach can diff results
        // across queries instead of rebuilding every row on each keystroke.
        var id: String { "\(era.name)::\(songOrdinal)::\(song.baseName)::\(version.id)" }
    }

    /// Upper bound on search rows handed to the list. Highest-scoring first,
    /// so the cut only ever drops weak matches.
    nonisolated static let maxSearchResults = 500

    private nonisolated static func computeSearchResults(
        artist: Artist, state: FilterState, searchIndex: [[SongSearchFields]]
    ) -> [SearchResult] {
        let q = state.query
        guard !q.isEmpty else { return [] }
        // Use the prebuilt haystack when its shape matches; otherwise fall back
        // to inline scoring so correctness never depends on the index.
        let useIndex = searchIndex.count == artist.eras.count
        var results: [SearchResult] = []
        for (eraIdx, era) in artist.eras.enumerated() {
            if Task.isCancelled { return [] }
            let songs = era.allSongs
            let eraFields = (useIndex && searchIndex[eraIdx].count == songs.count) ? searchIndex[eraIdx] : nil
            for (songIdx, song) in songs.enumerated() {
                let score = eraFields.map { scoreSong(fields: $0[songIdx], query: q) }
                    ?? scoreSong(song, query: q)
                guard score > 0 else { continue }
                for version in song.versions {
                    if state.bestOf && !isBestOfVersion(version) { continue }
                    if state.worstOf && !isWorstOfVersion(version) { continue }
                    if state.grails && !isGrailOrWantedVersion(version) { continue }
                    if state.noSnippets && shouldFilterForNoSnippets(version) { continue }
                    results.append(SearchResult(song: song, version: version, era: era, score: score, songOrdinal: songIdx))
                }
            }
        }
        results.sort { $0.score > $1.score }
        // One result per *version*, uncapped, meant a 1-2 character query on a
        // large tracker built tens of thousands of rows — each copying a Song,
        // SongVersion and Era — and handed them all to a ForEach. Nobody
        // scrolls past a few hundred; the sort above keeps the best ones.
        return Array(results.prefix(Self.maxSearchResults))
    }

    // MARK: - Recents

    nonisolated struct RecentResult: Identifiable, Equatable, Sendable {
        let song: Song
        let version: SongVersion
        let era: Era
        let timestamp: TimeInterval
        /// Position of the song within its era's flattened list — disambiguates
        /// same-`baseName` songs (e.g. several "???" placeholders per era) whose
        /// ids would otherwise collide and be dropped by ForEach. See SearchResult.
        let songOrdinal: Int

        // Stable content-derived id — see DECISIONS.md::FilterPipeline.swift::stable-row-id
        var id: String { "\(era.name)::\(songOrdinal)::\(song.baseName)::\(version.id)" }
    }

    private nonisolated static func computeRecentResults(artist: Artist, state: FilterState) -> [RecentResult] {
        var results: [RecentResult] = []
        for era in artist.eras {
            if Task.isCancelled { return [] }
            for (songOrdinal, song) in era.allSongs.enumerated() {
                if state.bestOf {
                    let hasBestVersion = song.versions.contains { isBestOfVersion($0) }
                    if !hasBestVersion { continue }
                }
                if state.worstOf {
                    let hasWorstVersion = song.versions.contains { isWorstOfVersion($0) }
                    if !hasWorstVersion { continue }
                }
                if state.grails {
                    let hasGrail = song.versions.contains { isGrailOrWantedVersion($0) }
                    if !hasGrail { continue }
                }
                for version in song.versions {
                    if state.bestOf && !isBestOfVersion(version) { continue }
                    if state.worstOf && !isWorstOfVersion(version) { continue }
                    if state.grails && !isGrailOrWantedVersion(version) { continue }
                    if state.noSnippets && shouldFilterForNoSnippets(version) { continue }
                    // previewDate last: a leak/file date is the real event,
                    // but a preview-only version has nothing else, and those
                    // were invisible to Recents entirely.
                    let dateStr = [version.leakDate, version.fileDate, version.previewDate]
                        .compactMap { $0 }
                        .first { !$0.isEmpty }
                    guard let dateStr else { continue }
                    results.append(RecentResult(
                        song: song, version: version, era: era,
                        timestamp: parseLeakDate(dateStr), songOrdinal: songOrdinal
                    ))
                }
            }
        }
        results.sort { $0.timestamp > $1.timestamp }
        return results
    }

    // MARK: - Misc entries

    /// Misc entries after in-mode filters: No Snippets drops unavailable
    /// entries, Recent sorts by date descending, search matches name /
    /// notes / era / type. Best Of restricts to badge-marked names when any
    /// exist (misc entries usually carry no badges — then it's a no-op).
    /// Group a content tab's entries by era, in the artist's own era order.
    ///
    /// `eraOrder` is the era tree's ordering. Grouping alone used to emit
    /// groups in sheet-row order, which put whatever the tab happened to list
    /// first at the top: on the Ye Misc tab that was "Opt Archive", "Twitter"
    /// and "Pierre-Louis Auvray" — 4 entries out of 747, each a source name
    /// the sheet put in its Era column — sitting above every real era with a
    /// placeholder cover. Ordering by the era tree makes a content tab read in
    /// the same sequence as the Unreleased list.
    ///
    /// Groups whose name matches no era keep their relative order and go last:
    /// they are real content, so they must not be dropped, but they are also
    /// not eras and should not lead.
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
        for (i, name) in eraOrder.enumerated() {
            rank[Self.eraMatchKey(name)] = i
        }
        let sorted = order.enumerated().sorted { lhs, rhs in
            let l = rank[Self.eraMatchKey(lhs.element)]
            let r = rank[Self.eraMatchKey(rhs.element)]
            switch (l, r) {
            case let (l?, r?): return l == r ? lhs.offset < rhs.offset : l < r
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

    private nonisolated static func computeMiscResults(artist: Artist, state: FilterState) -> [MiscEntry] {
        // A selected tab sources that tab's entries; the legacy misc mode
        // reads the flat misc/MV list (older cached payloads have no tabs).
        var entries: [MiscEntry]
        if let tabKey = state.tabKey {
            entries = artist.tabs?.first(where: { $0.id == tabKey })?.entries ?? []
        } else {
            entries = artist.miscEntries ?? []
        }
        if state.noSnippets {
            entries = entries.filter { !isSnippetLike(available: $0.available, quality: $0.quality) }
        }
        if state.bestOf {
            // Match only best/special emojis — the same set the song-version
            // Best Of uses (isBestOfVersion). Matching every Badge case here
            // wrongly surfaced worst-of (🗑️) and AI (🤖) entries under Best Of.
            let starred = entries.filter { e in
                Badge.allCases.contains { $0.isBestOf && e.name.contains($0.emoji) }
            }
            if !starred.isEmpty { entries = starred }
        }
        if state.worstOf {
            let flagged = entries.filter { $0.name.contains(Badge.worst.emoji) }
            if !flagged.isEmpty { entries = flagged }
        }
        if state.grails {
            // The chip was doing nothing at all on a content tab: every other
            // badge filter was honoured here and this one was simply missing.
            // Grail + wanted, matching the eras branch's combined chip.
            let sought = entries.filter { e in
                e.name.contains(Badge.grail.emoji) || e.name.contains(Badge.wanted.emoji)
            }
            if !sought.isEmpty { entries = sought }
        }
        if !state.query.isEmpty {
            let q = state.query
            entries = entries.filter { e in
                e.name.lowercased().contains(q)
                    || (e.notes ?? "").lowercased().contains(q)
                    || e.eraName.lowercased().contains(q)
                    || (e.entryType ?? "").lowercased().contains(q)
            }
        }
        if state.recents {
            entries = entries.sorted {
                Self.parseLeakDate($0.date ?? "") > Self.parseLeakDate($1.date ?? "")
            }
        }
        return entries
    }

    // MARK: - Stats

    nonisolated struct Stats: Equatable, Sendable {
        let total: Int
        let available: Int
        let snippets: Int
        let confirmed: Int
        let fullHQ: Int
    }

    /// Same shape as `computeEraStats`, over a content tab's entries.
    ///
    /// Without this the stats bar kept showing the era tree's totals while a
    /// content tab was on screen, so the header claimed 9,368 tracks over a
    /// list of 747 released entries.
    nonisolated static func computeTabStats(_ entries: [MiscEntry]) -> Stats {
        var total = 0, available = 0, snippets = 0, confirmed = 0, fullHQ = 0
        for entry in entries {
            total += 1
            let al = (entry.available ?? "").lowercased()
            let q = (entry.quality ?? "").lowercased()
            if entry.isStreamable { available += 1 }
            if al.contains("snippet") { snippets += 1 }
            if al.contains("confirmed") && !entry.isStreamable { confirmed += 1 }
            let isFull = al.contains("full") || al.contains("near full") || al.contains("og file")
            let isHQ = q.contains("hq") || q.contains("high") || q.contains("cd")
                || q.contains("lossless") || q.contains("og")
            if isFull && isHQ { fullHQ += 1 }
        }
        return Stats(
            total: total, available: available, snippets: snippets,
            confirmed: confirmed, fullHQ: fullHQ
        )
    }

    nonisolated static func computeEraStats(_ era: Era) -> Stats {
        var total = 0, available = 0, snippets = 0, confirmed = 0, fullHQ = 0
        for song in era.allSongs {
            for v in song.versions {
                total += 1
                let al = (v.availableLength ?? "").lowercased()
                let q = (v.quality ?? "").lowercased()
                if v.isStreamable { available += 1 }
                if al.contains("snippet") { snippets += 1 }
                if al.contains("confirmed") && !v.isStreamable { confirmed += 1 }
                let isFull = al.contains("full") || al.contains("near full") || al.contains("og file")
                let isHQ = q.contains("hq") || q.contains("high") || q.contains("cd") || q.contains("lossless") || q.contains("og")
                if isFull && isHQ { fullHQ += 1 }
            }
        }
        return Stats(total: total, available: available, snippets: snippets, confirmed: confirmed, fullHQ: fullHQ)
    }

    // MARK: - Private helpers

    // Badge.isBestOf is the single predicate (matches web's BEST_OF_BADGES).
    private nonisolated static func isBestOfVersion(_ v: SongVersion) -> Bool {
        v.badge.flatMap { Badge(rawValue: $0) }?.isBestOf ?? false
    }

    private nonisolated static func isWorstOfVersion(_ v: SongVersion) -> Bool {
        v.badge.flatMap { Badge(rawValue: $0) } == .worst
    }

    /// The combined "grails" filter — the grail and wanted badges together
    /// (the most sought-after tracks), surfaced as one chip.
    private nonisolated static func isGrailOrWantedVersion(_ v: SongVersion) -> Bool {
        guard let badge = v.badge.flatMap({ Badge(rawValue: $0) }) else { return false }
        return badge == .grail || badge == .wanted
    }

    /// Prebuilt lowercased search fields for one song (see Precomputed.searchIndex).
    nonisolated struct SongSearchFields: Sendable {
        let baseName: String
        let altTitles: [String]
        let versionNames: [String]

        init(song: Song) {
            baseName = song.baseName.lowercased()
            var alts: [String] = []
            var names: [String] = []
            for v in song.versions {
                if let a = v.altTitles { alts.append(contentsOf: a.map { $0.lowercased() }) }
                names.append(v.name.lowercased())
            }
            altTitles = alts
            versionNames = names
        }
    }

    /// Index-backed scorer — MUST stay identical in ranking to
    /// `scoreSong(_ song:query:)` below (the FilterPipelineTests pin the order).
    private nonisolated static func scoreSong(fields: SongSearchFields, query: String) -> Int {
        if fields.baseName == query { return 100 }
        if fields.altTitles.contains(query) { return 90 }
        if fields.baseName.hasPrefix(query) { return 70 }
        if fields.altTitles.contains(where: { $0.hasPrefix(query) }) { return 60 }
        if fields.baseName.contains(query) { return 40 }
        if fields.versionNames.contains(where: { $0.contains(query) }) { return 20 }
        if fields.altTitles.contains(where: { $0.contains(query) }) { return 20 }
        return 0
    }

    private nonisolated static func scoreSong(_ song: Song, query: String) -> Int {
        let bn = song.baseName.lowercased()
        var alts: [String] = []
        for v in song.versions {
            if let altTitles = v.altTitles {
                alts.append(contentsOf: altTitles.map { $0.lowercased() })
            }
        }
        if bn == query { return 100 }
        if alts.contains(query) { return 90 }
        if bn.hasPrefix(query) { return 70 }
        if alts.contains(where: { $0.hasPrefix(query) }) { return 60 }
        if bn.contains(query) { return 40 }
        for v in song.versions {
            if v.name.lowercased().contains(query) { return 20 }
        }
        if alts.contains(where: { $0.contains(query) }) { return 20 }
        return 0
    }

    /// Shared No-Snippets predicate for song versions AND misc entries.
    nonisolated static func isSnippetLike(available: String?, quality: String?) -> Bool {
        let al = (available ?? "").lowercased()
        let q = (quality ?? "").lowercased()
        return al.contains("snippet") || al.contains("unavailable") || q.contains("not available")
    }

    private nonisolated static func shouldFilterForNoSnippets(_ v: SongVersion) -> Bool {
        isSnippetLike(available: v.availableLength, quality: v.quality)
    }

    // MARK: - Date parsing (cached formatters, safe to call from any thread)

    private nonisolated static let _slashFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MM/dd/yyyy"
        return f
    }()

    private nonisolated static let _isoFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private nonisolated static let _monthYearFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMMM yyyy"
        return f
    }()

    private nonisolated static let _yearFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy"
        return f
    }()

    // Dominant date format — see DECISIONS.md::FilterPipeline.swift::date-format-priority
    private nonisolated static let _abbrevMonthDayFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMM d, yyyy"
        return f
    }()

    // "March 20, 2023"
    private nonisolated static let _fullMonthDayFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMMM d, yyyy"
        return f
    }()

    // "Mar 2023"
    private nonisolated static let _abbrevMonthYearFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMM yyyy"
        return f
    }()

    // "20 Mar 2023" / "20 March 2023" — day-first ordering, which none of the
    // month-first formatters accept (it degraded to year-only).
    private nonisolated static let _dayFirstFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "d MMM yyyy"
        return f
    }()

    // ISO-8601 w/ time — see DECISIONS.md::FilterPipeline.swift::iso8601-formatter
    private nonisolated static let _iso8601Fmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXXXX"
        return f
    }()

    // Internal (not private) so LeakSheetTests can pin the accepted formats.
    nonisolated static func parseLeakDate(_ dateStr: String) -> TimeInterval {
        if let d = _slashFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _isoFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _iso8601Fmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _dayFirstFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _abbrevMonthDayFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _fullMonthDayFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _monthYearFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _abbrevMonthYearFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        // Extract bare year with Swift Regex (compile-time checked)
        if let match = dateStr.firstMatch(of: /(\d{4})/),
           let d = _yearFmt.date(from: String(match.output.1)) {
            return d.timeIntervalSince1970
        }
        return 0
    }
}
