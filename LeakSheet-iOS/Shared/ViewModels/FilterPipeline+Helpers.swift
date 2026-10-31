import Foundation

extension ArtistViewModel {
    // MARK: - Stats

    nonisolated struct Stats: Equatable, Sendable {
        let total: Int
        let available: Int
        let snippets: Int
        let confirmed: Int
        let fullHQ: Int
    }

    /// Same shape as `computeEraStats`, over a content tab's entries, so the stats
    /// bar describes the tab on screen.
    nonisolated static func computeTabStats(_ entries: [MiscEntry]) -> Stats {
        tally(entries, available: \.available, quality: \.quality, streamable: \.isStreamable)
    }

    nonisolated static func computeEraStats(_ era: Era) -> Stats {
        // .lazy: `allSongs` is itself a flatMap, so an eager one here would
        // materialise a second full-size array per era just to count it.
        tally(
            era.allSongs.lazy.flatMap(\.versions),
            available: \.availableLength,
            quality: \.quality,
            streamable: \.isStreamable
        )
    }

    private nonisolated static func tally<S: Sequence>(
        _ items: S,
        available: (S.Element) -> String?,
        quality: (S.Element) -> String?,
        streamable: (S.Element) -> Bool
    ) -> Stats {
        var total = 0, availableCount = 0, snippets = 0, confirmed = 0, fullHQ = 0
        for item in items {
            total += 1
            let al = (available(item) ?? "").lowercased()
            let q = (quality(item) ?? "").lowercased()
            let isStreamable = streamable(item)
            if isStreamable { availableCount += 1 }
            if al.contains("snippet") { snippets += 1 }
            if al.contains("confirmed") && !isStreamable { confirmed += 1 }
            let isFull = al.contains("full") || al.contains("near full") || al.contains("og file")
            let isHQ = q.contains("hq") || q.contains("high") || q.contains("cd")
                || q.contains("lossless") || q.contains("og")
            if isFull && isHQ { fullHQ += 1 }
        }
        return Stats(
            total: total, available: availableCount, snippets: snippets,
            confirmed: confirmed, fullHQ: fullHQ
        )
    }

    // MARK: - Private helpers

    // Badge.isBestOf is the single predicate (matches web's BEST_OF_BADGES).
    nonisolated static func isBestOfVersion(_ v: SongVersion) -> Bool {
        v.badge.flatMap { Badge(rawValue: $0) }?.isBestOf ?? false
    }

    nonisolated static func isWorstOfVersion(_ v: SongVersion) -> Bool {
        v.badge.flatMap { Badge(rawValue: $0) } == .worst
    }

    /// The combined "grails" filter — the grail and wanted badges together
    /// (the most sought-after tracks), surfaced as one chip.
    nonisolated static func isGrailOrWantedVersion(_ v: SongVersion) -> Bool {
        guard let badge = v.badge.flatMap({ Badge(rawValue: $0) }) else { return false }
        return badge == .grail || badge == .wanted
    }

    /// Prebuilt lowercased search fields for one song (see Precomputed.searchIndex).
    nonisolated struct SongSearchFields: Sendable {
        let baseName: String
        let altTitles: [String]
        let versionNames: [String]

        init(song: Song) {
            baseName = Song.nameKey(song.baseName)
            var alts: [String] = []
            var names: [String] = []
            for v in song.versions {
                if let a = v.altTitles { alts.append(contentsOf: a.map(Song.nameKey)) }
                names.append(Song.nameKey(v.name))
            }
            altTitles = alts
            versionNames = names
        }
    }

    /// Index-backed scorer — MUST stay identical in ranking to
    /// `scoreSong(_ song:query:)` below (the FilterPipelineTests pin the order).
    nonisolated static func scoreSong(fields: SongSearchFields, query: String) -> Int {
        if fields.baseName == query { return 100 }
        if fields.altTitles.contains(query) { return 90 }
        if fields.baseName.hasPrefix(query) { return 70 }
        if fields.altTitles.contains(where: { $0.hasPrefix(query) }) { return 60 }
        if fields.baseName.contains(query) { return 40 }
        if fields.versionNames.contains(where: { $0.contains(query) }) { return 20 }
        if fields.altTitles.contains(where: { $0.contains(query) }) { return 20 }
        return 0
    }

    nonisolated static func scoreSong(_ song: Song, query: String) -> Int {
        let bn = Song.nameKey(song.baseName)
        var alts: [String] = []
        for v in song.versions {
            if let altTitles = v.altTitles {
                alts.append(contentsOf: altTitles.map(Song.nameKey))
            }
        }
        if bn == query { return 100 }
        if alts.contains(query) { return 90 }
        if bn.hasPrefix(query) { return 70 }
        if alts.contains(where: { $0.hasPrefix(query) }) { return 60 }
        if bn.contains(query) { return 40 }
        for v in song.versions {
            if Song.nameKey(v.name).contains(query) { return 20 }
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

    nonisolated static func shouldFilterForNoSnippets(_ v: SongVersion) -> Bool {
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

    // "20 Mar 2023" / "20 March 2023": day-first, which no month-first formatter accepts.
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

    // "3/5/19": US order like the four-digit form; yy maps into a 1950–2049 window.
    private nonisolated static let _shortYearSlashFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "M/d/yy"
        return f
    }()

    /// "Sept 13th, 1996", "Sep. 13 1996", "13th September 1996" → shapes the formatters accept.
    nonisolated static func normalizedDate(_ raw: String) -> String {
        var s = raw.trimmingCharacters(in: .whitespaces)
        s = s.replacing(/(\d{1,2})(?:st|nd|rd|th)\b/) { String($0.output.1) }
        s = s.replacing(/\b(Sept)\b\.?/.ignoresCase()) { _ in "Sep" }
        s = s.replacing(/\b([A-Za-z]{3})\.(?=\s)/) { String($0.output.1) }
        // "Sep 13 1996" → "Sep 13, 1996"; a full month name is shortened so one formatter fits.
        s = s.replacing(/^([A-Za-z]+) (\d{1,2}) (\d{4})$/) { "\($0.output.1) \($0.output.2), \($0.output.3)" }
        s = s.replacing(/^(\d{1,2}) ([A-Za-z]{4,}) (\d{4})$/) {
            "\($0.output.1) \($0.output.2.prefix(3)) \($0.output.3)"
        }
        return s
    }

    // Internal (not private) so LeakSheetTests can pin the accepted formats.
    nonisolated static func parseLeakDate(_ dateStr: String) -> TimeInterval {
        if let t = exactDate(dateStr) { return t }
        // Irregular spellings keep day precision instead of collapsing to the year.
        let normalized = normalizedDate(dateStr)
        if normalized != dateStr, let t = exactDate(normalized) { return t }
        // Extract bare year with Swift Regex (compile-time checked)
        if let match = dateStr.firstMatch(of: /(\d{4})/),
           let d = _yearFmt.date(from: String(match.output.1)) {
            return d.timeIntervalSince1970
        }
        return 0
    }

    private nonisolated static func exactDate(_ dateStr: String) -> TimeInterval? {
        // Before the four-digit form, which reads "03/20/23" as the year 23.
        if dateStr.wholeMatch(of: /\d{1,2}\/\d{1,2}\/\d{2}/) != nil {
            return _shortYearSlashFmt.date(from: dateStr)?.timeIntervalSince1970
        }
        if let d = _slashFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _isoFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _iso8601Fmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _dayFirstFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _abbrevMonthDayFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _fullMonthDayFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _monthYearFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        if let d = _abbrevMonthYearFmt.date(from: dateStr) { return d.timeIntervalSince1970 }
        return nil
    }
}
