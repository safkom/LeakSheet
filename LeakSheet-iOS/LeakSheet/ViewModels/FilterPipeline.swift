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
                miscEraGroups: groupMiscByEra(miscResults)
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
        return results
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

        // Stable content-derived id so SwiftUI's ForEach can diff results
        // across filter/query changes instead of rebuilding every row each
        // keystroke (a fresh UUID() on every rebuild caused row flicker
        // and lost expand state).
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
                    let dateStr = version.leakDate ?? version.fileDate
                    guard let dateStr, !dateStr.isEmpty else { continue }
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
    nonisolated static func groupMiscByEra(_ entries: [MiscEntry]) -> [MiscEraGroup] {
        var order: [String] = []
        var byEra: [String: [MiscEntry]] = [:]
        for entry in entries {
            if byEra[entry.eraName] == nil { order.append(entry.eraName) }
            byEra[entry.eraName, default: []].append(entry)
        }
        return order.map { MiscEraGroup(eraName: $0, entries: byEra[$0] ?? []) }
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

    // "Mar 20, 2023" — the DOMINANT format across live trackers (86% of all
    // dated versions in the 2026-07-20 TrackerHub sweep, incl. the whole Ye
    // tracker). Without it every such date degraded to year-only precision
    // and Recents ordering within a year was arbitrary.
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

    // Full ISO-8601 with a time component ("2023-03-20T14:30:00Z"). The web
    // reference gets these free via Date.parse; _isoFmt's strict "yyyy-MM-dd"
    // rejects them, so they too fell back to the bare-year bucket.
    // DateFormatter (not ISO8601DateFormatter) because only the former is
    // Sendable, which a nonisolated static requires under Swift 6.
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
