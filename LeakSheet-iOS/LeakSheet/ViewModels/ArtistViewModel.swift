import Foundation
import SwiftUI
import Observation
import Combine

/// ViewModel for artist detail screen — search, filter, era state.
@MainActor
@Observable
final class ArtistViewModel {
    // MARK: - Input

    let artist: Artist

    // MARK: - Search

    var searchQuery: String = "" {
        didSet { scheduleDebounce() }
    }
    private(set) var debouncedQuery: String = ""
    private var debounceTask: Task<Void, Never>?

    // MARK: - Filters

    var bestOf: Bool = false
    var recents: Bool = false
    var noSnippets: Bool = false
    var expandedEra: String? = nil

    // MARK: - State

    var isSearching: Bool { !debouncedQuery.isEmpty }

    // MARK: - Image prefetch

    private(set) var imagesReady: Bool = false
    /// Per-era extracted colors, populated during prefetch.
    private(set) var prefetchedColors: [String: Color] = [:]

    func prefetchEraImages() async {
        let urls: [(eraName: String, url: URL)] = artist.eras.compactMap { era in
            guard let artUrl = era.artUrl,
                  let url = APIClient.shared.imageProxyURL(for: artUrl) else { return nil }
            return (era.name, url)
        }
        guard !urls.isEmpty else {
            imagesReady = true
            return
        }
        // Download all images + extract colors in parallel
        var colors: [String: Color] = [:]
        await withTaskGroup(of: (String, Color?).self) { group in
            for (eraName, url) in urls {
                group.addTask {
                    guard let image = await ImageCache.shared.loadImage(from: url) else {
                        return (eraName, nil)
                    }
                    let color = await EraColorExtractor.shared.extractColor(fromImage: image, eraName: eraName)
                    return (eraName, color)
                }
            }
            for await (eraName, color) in group {
                if let color { colors[eraName] = color }
            }
        }
        prefetchedColors = colors
        imagesReady = true
    }

    // MARK: - Recents cache

    private(set) var cachedRecentResults: [RecentResult] = []
    private(set) var recentsLoading: Bool = false

    // MARK: - Init

    init(artist: Artist) {
        self.artist = artist
    }

    // MARK: - Debounce

    private func scheduleDebounce() {
        debounceTask?.cancel()
        let q = searchQuery.trimmingCharacters(in: .whitespaces)
        if q.isEmpty {
            debouncedQuery = ""
            invalidateRecentsCache()
            return
        }
        debounceTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled else { return }
            self?.debouncedQuery = q
            self?.invalidateRecentsCache()
        }
    }

    // MARK: - Filtered eras

    var filteredEras: [Era] {
        var result = artist.eras.filter { !$0.allSongs.isEmpty }
        if bestOf {
            result = result.filter { era in
                era.allSongs.contains { song in
                    song.versions.contains { v in
                        guard let badge = v.badge.flatMap({ Badge(rawValue: $0) }) else { return false }
                        return Self.bestOfBadges.contains(badge)
                    }
                }
            }
        }
        let q = debouncedQuery.lowercased()
        guard !q.isEmpty else { return result }
        return result.filter { era in
            if era.name.lowercased().contains(q) { return true }
            if era.altNames?.contains(where: { $0.lowercased().contains(q) }) == true { return true }
            return era.allSongs.contains { songMatchesQuery($0, query: q) }
        }
    }

    // MARK: - Filtered songs for a given era

    func filteredSongs(for era: Era) -> [Song] {
        var songs = era.allSongs
        if bestOf { songs = filterToBestOf(songs) }
        if noSnippets { songs = filterNoSnippets(songs) }
        let q = debouncedQuery.lowercased()
        guard !q.isEmpty else { return songs }
        let eraMatch = era.name.lowercased().contains(q) ||
            era.altNames?.contains(where: { $0.lowercased().contains(q) }) == true
        if eraMatch { return songs }
        return songs.filter { songMatchesQuery($0, query: q) }
    }

    // MARK: - Filtered sections for a given era

    func filteredSections(for era: Era) -> [Section] {
        guard let sections = era.sections else { return [] }
        let q = debouncedQuery.lowercased()
        let filtering = bestOf || !q.isEmpty || noSnippets
        guard filtering else { return sections }

        return sections.compactMap { sec in
            var songs = sec.songs
            if bestOf { songs = filterToBestOf(songs) }
            if noSnippets { songs = filterNoSnippets(songs) }
            if !q.isEmpty {
                let eraMatch = era.name.lowercased().contains(q) ||
                    era.altNames?.contains(where: { $0.lowercased().contains(q) }) == true
                if !eraMatch {
                    songs = songs.filter { songMatchesQuery($0, query: q) }
                }
            }
            guard !songs.isEmpty else { return nil }
            return Section(name: sec.name, group: sec.group, songs: songs)
        }
    }

    // MARK: - Flat search results (ranked)

    struct SearchResult: Identifiable, Hashable {
        let song: Song
        let version: SongVersion
        let era: Era
        let score: Int

        // Stable id derived from content so SwiftUI's ForEach can diff results
        // across queries instead of rebuilding every row on each keystroke.
        var id: String { "\(era.name)::\(song.baseName)::\(version.id)" }
    }

    /// Search against an explicit query string — does NOT affect filteredEras.
    /// Used by the search overlay so the background era list stays unfiltered.
    func searchResults(for rawQuery: String) -> [SearchResult] {
        let q = rawQuery.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return [] }
        var results: [SearchResult] = []
        for era in artist.eras {
            for song in era.allSongs {
                let score = scoreSong(song, query: q)
                guard score > 0 else { continue }
                for version in song.versions {
                    if bestOf {
                        guard let vBadge = version.badge.flatMap({ Badge(rawValue: $0) }),
                              Self.bestOfBadges.contains(vBadge) else { continue }
                    }
                    if noSnippets && isSnippet(version) { continue }
                    results.append(SearchResult(song: song, version: version, era: era, score: score))
                }
            }
        }
        results.sort { $0.score > $1.score }
        return results
    }

    // MARK: - Recents (sorted by leak date, cached)

    struct RecentResult: Identifiable {
        let id = UUID()
        let song: Song
        let version: SongVersion
        let era: Era
        let timestamp: TimeInterval
    }

    private var recentsTask: Task<Void, Never>?

    private func invalidateRecentsCache() {
        guard recents else { return }
        computeRecentsAsync()
    }

    private func computeRecentsAsync() {
        recentsTask?.cancel()
        recentsLoading = true
        let artist = self.artist
        let bestOf = self.bestOf
        let noSnippets = self.noSnippets
        let query = self.debouncedQuery.lowercased()
        let bestOfBadges = Self.bestOfBadges
        recentsTask = Task.detached(priority: .userInitiated) {
            let results = Self.buildRecentResults(
                artist: artist, bestOf: bestOf,
                noSnippets: noSnippets, query: query,
                bestOfBadges: bestOfBadges
            )
            guard !Task.isCancelled else { return }
            await MainActor.run { [weak self] in
                self?.cachedRecentResults = results
                self?.recentsLoading = false
            }
        }
    }

    private nonisolated static func buildRecentResults(
        artist: Artist,
        bestOf: Bool,
        noSnippets: Bool,
        query: String,
        bestOfBadges: Set<Badge>
    ) -> [RecentResult] {
        var results: [RecentResult] = []
        for era in artist.eras {
            for song in era.allSongs {
                if bestOf {
                    let hasBestVersion = song.versions.contains { v in
                        guard let badge = v.badge.flatMap({ Badge(rawValue: $0) }) else { return false }
                        return bestOfBadges.contains(badge)
                    }
                    if !hasBestVersion { continue }
                }
                if !query.isEmpty {
                    let searchText = buildSearchTextStatic(song)
                    if !searchText.contains(query) { continue }
                }
                for version in song.versions {
                    if bestOf {
                        guard let badge = version.badge.flatMap({ Badge(rawValue: $0) }),
                              bestOfBadges.contains(badge) else { continue }
                    }
                    if noSnippets && shouldFilterForNoSnippets(version) { continue }
                    let dateStr = version.leakDate ?? version.fileDate
                    guard let dateStr, !dateStr.isEmpty else { continue }
                    results.append(RecentResult(
                        song: song, version: version, era: era,
                        timestamp: parseLeakDate(dateStr)
                    ))
                }
            }
        }
        results.sort { $0.timestamp > $1.timestamp }
        return results
    }

    private nonisolated static func buildSearchTextStatic(_ song: Song) -> String {
        var parts = [song.baseName.lowercased()]
        for v in song.versions {
            parts.append(v.name.lowercased())
            if let alts = v.altTitles {
                parts.append(contentsOf: alts.map { $0.lowercased() })
            }
        }
        return parts.joined(separator: "\0")
    }

    // MARK: - Era expand/collapse

    func toggleEra(_ name: String) {
        if bestOf { return }
        expandedEra = expandedEra == name ? nil : name
    }

    func isEraExpanded(_ name: String) -> Bool {
        if bestOf { return true }
        return expandedEra == name
    }

    func toggleBestOf() {
        bestOf.toggle()
        if !bestOf && !recents { expandedEra = nil }
        invalidateRecentsCache()
    }

    func toggleRecents() {
        recents.toggle()
        if !recents {
            cachedRecentResults = []
            if !bestOf { expandedEra = nil }
        } else {
            computeRecentsAsync()
        }
    }

    func toggleNoSnippets() {
        noSnippets.toggle()
        invalidateRecentsCache()
    }

    // MARK: - Stats

    struct Stats {
        let total: Int
        let available: Int
        let snippets: Int
        let confirmed: Int
        let fullHQ: Int
    }

    var artistStats: Stats {
        var total = 0, available = 0, snippets = 0, confirmed = 0, fullHQ = 0
        for era in artist.eras {
            let s = eraStats(era)
            total += s.total
            available += s.available
            snippets += s.snippets
            confirmed += s.confirmed
            fullHQ += s.fullHQ
        }
        return Stats(total: total, available: available, snippets: snippets, confirmed: confirmed, fullHQ: fullHQ)
    }

    func eraStats(_ era: Era) -> Stats {
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

    // Matches web's BEST_OF_BADGES = new Set(['best', 'special'])
    private static let bestOfBadges: Set<Badge> = [.best, .special]

    private func isBestOfSong(_ song: Song) -> Bool {
        song.versions.contains { v in
            guard let badge = v.badge.flatMap({ Badge(rawValue: $0) }) else { return false }
            return Self.bestOfBadges.contains(badge)
        }
    }

    private func songMatchesQuery(_ song: Song, query: String) -> Bool {
        let searchText = buildSearchText(song)
        return searchText.contains(query)
    }

    private func scoreSong(_ song: Song, query: String) -> Int {
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

    private func buildSearchText(_ song: Song) -> String {
        var parts = [song.baseName.lowercased()]
        for v in song.versions {
            parts.append(v.name.lowercased())
            if let alts = v.altTitles {
                parts.append(contentsOf: alts.map { $0.lowercased() })
            }
        }
        return parts.joined(separator: "\0")
    }

    private func filterToBestOf(_ songs: [Song]) -> [Song] {
        songs.compactMap { song in
            song.withFilteredVersions { v in
                guard let badge = v.badge.flatMap({ Badge(rawValue: $0) }) else { return false }
                return Self.bestOfBadges.contains(badge)
            }
        }
    }

    private func filterNoSnippets(_ songs: [Song]) -> [Song] {
        songs.compactMap { song in
            song.withFilteredVersions { !isSnippet($0) }
        }
    }

    private func isSnippet(_ v: SongVersion) -> Bool {
        Self.shouldFilterForNoSnippets(v)
    }

    private nonisolated static func shouldFilterForNoSnippets(_ v: SongVersion) -> Bool {
        let al = (v.availableLength ?? "").lowercased()
        let q = (v.quality ?? "").lowercased()
        return al.contains("snippet") || al.contains("unavailable") || q.contains("not available")
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

    private nonisolated static func parseLeakDate(_ dateStr: String) -> TimeInterval {
        if let d = _slashFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _isoFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _monthYearFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        // Extract bare year with Swift Regex (compile-time checked)
        if let match = dateStr.firstMatch(of: /(\d{4})/),
           let d = _yearFmt.date(from: String(match.output.1)) {
            return d.timeIntervalSince1970
        }
        return 0
    }
}
