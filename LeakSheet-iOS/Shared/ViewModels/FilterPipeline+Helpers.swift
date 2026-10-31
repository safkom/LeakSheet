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
            let availableKey = (available(item) ?? "").lowercased()
            let qualityKey = (quality(item) ?? "").lowercased()
            let isStreamable = streamable(item)
            if isStreamable { availableCount += 1 }
            if availableKey.contains("snippet") { snippets += 1 }
            if availableKey.contains("confirmed") && !isStreamable { confirmed += 1 }
            let isFull = availableKey.contains("full") || availableKey.contains("near full")
                || availableKey.contains("og file")
            let isHQ = qualityKey.contains("hq") || qualityKey.contains("high") || qualityKey.contains("cd")
                || qualityKey.contains("lossless") || qualityKey.contains("og")
            if isFull && isHQ { fullHQ += 1 }
        }
        return Stats(
            total: total, available: availableCount, snippets: snippets,
            confirmed: confirmed, fullHQ: fullHQ
        )
    }

    // MARK: - Private helpers

    // Badge.isBestOf is the single predicate (matches web's BEST_OF_BADGES).
    nonisolated static func isBestOfVersion(_ version: SongVersion) -> Bool {
        version.badge.flatMap { Badge(rawValue: $0) }?.isBestOf ?? false
    }

    nonisolated static func isWorstOfVersion(_ version: SongVersion) -> Bool {
        version.badge.flatMap { Badge(rawValue: $0) } == .worst
    }

    /// The combined "grails" filter — the grail and wanted badges together
    /// (the most sought-after tracks), surfaced as one chip.
    nonisolated static func isGrailOrWantedVersion(_ version: SongVersion) -> Bool {
        guard let badge = version.badge.flatMap({ Badge(rawValue: $0) }) else { return false }
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
            for version in song.versions {
                if let altList = version.altTitles { alts.append(contentsOf: altList.map(Song.nameKey)) }
                names.append(Song.nameKey(version.name))
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
        let baseKey = Song.nameKey(song.baseName)
        var alts: [String] = []
        for version in song.versions {
            if let altTitles = version.altTitles {
                alts.append(contentsOf: altTitles.map(Song.nameKey))
            }
        }
        if baseKey == query { return 100 }
        if alts.contains(query) { return 90 }
        if baseKey.hasPrefix(query) { return 70 }
        if alts.contains(where: { $0.hasPrefix(query) }) { return 60 }
        if baseKey.contains(query) { return 40 }
        if song.versions.contains(where: { Song.nameKey($0.name).contains(query) }) { return 20 }
        if alts.contains(where: { $0.contains(query) }) { return 20 }
        return 0
    }

    /// Shared No-Snippets predicate for song versions AND misc entries.
    nonisolated static func isSnippetLike(available: String?, quality: String?) -> Bool {
        let availableKey = (available ?? "").lowercased()
        let qualityKey = (quality ?? "").lowercased()
        return availableKey.contains("snippet") || availableKey.contains("unavailable")
            || qualityKey.contains("not available")
    }

    nonisolated static func shouldFilterForNoSnippets(_ version: SongVersion) -> Bool {
        isSnippetLike(available: version.availableLength, quality: version.quality)
    }

    // MARK: - Date parsing (cached formatters, safe to call from any thread)

    private nonisolated static let _slashFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM/dd/yyyy"
        return formatter
    }()

    private nonisolated static let _isoFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private nonisolated static let _monthYearFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMMM yyyy"
        return formatter
    }()

    private nonisolated static let _yearFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy"
        return formatter
    }()

    // Dominant date format — see DECISIONS.md::FilterPipeline.swift::date-format-priority
    private nonisolated static let _abbrevMonthDayFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMM d, yyyy"
        return formatter
    }()

    // "March 20, 2023"
    private nonisolated static let _fullMonthDayFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMMM d, yyyy"
        return formatter
    }()

    // "Mar 2023"
    private nonisolated static let _abbrevMonthYearFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMM yyyy"
        return formatter
    }()

    // "20 Mar 2023" / "20 March 2023": day-first, which no month-first formatter accepts.
    private nonisolated static let _dayFirstFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "d MMM yyyy"
        return formatter
    }()

    // ISO-8601 w/ time — see DECISIONS.md::FilterPipeline.swift::iso8601-formatter
    private nonisolated static let _iso8601Fmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXXXX"
        return formatter
    }()

    // "3/5/19": US order like the four-digit form; yy maps into a 1950–2049 window.
    private nonisolated static let _shortYearSlashFmt: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "M/d/yy"
        return formatter
    }()

    /// "Sept 13th, 1996", "Sep. 13 1996", "13th September 1996" → shapes the formatters accept.
    nonisolated static func normalizedDate(_ raw: String) -> String {
        var text = raw.trimmingCharacters(in: .whitespaces)
        text = text.replacing(/(\d{1,2})(?:st|nd|rd|th)\b/) { String($0.output.1) }
        text = text.replacing(/\b(Sept)\b\.?/.ignoresCase()) { _ in "Sep" }
        text = text.replacing(/\b([A-Za-z]{3})\.(?=\s)/) { String($0.output.1) }
        // "Sep 13 1996" → "Sep 13, 1996"; a full month name is shortened so one formatter fits.
        text = text.replacing(/^([A-Za-z]+) (\d{1,2}) (\d{4})$/) { "\($0.output.1) \($0.output.2), \($0.output.3)" }
        text = text.replacing(/^(\d{1,2}) ([A-Za-z]{4,}) (\d{4})$/) {
            "\($0.output.1) \($0.output.2.prefix(3)) \($0.output.3)"
        }
        return text
    }

    // Internal (not private) so LeakSheetTests can pin the accepted formats.
    nonisolated static func parseLeakDate(_ dateStr: String) -> TimeInterval {
        if let time = exactDate(dateStr) { return time }
        // Irregular spellings keep day precision instead of collapsing to the year.
        let normalized = normalizedDate(dateStr)
        if normalized != dateStr, let time = exactDate(normalized) { return time }
        // Extract bare year with Swift Regex (compile-time checked)
        if let match = dateStr.firstMatch(of: /(\d{4})/),
           let date = _yearFmt.date(from: String(match.output.1)) {
            return date.timeIntervalSince1970
        }
        return 0
    }

    private nonisolated static func exactDate(_ dateStr: String) -> TimeInterval? {
        // Before the four-digit form, which reads "03/20/23" as the year 23.
        if dateStr.wholeMatch(of: /\d{1,2}\/\d{1,2}\/\d{2}/) != nil {
            return _shortYearSlashFmt.date(from: dateStr)?.timeIntervalSince1970
        }
        if let date = _slashFmt.date(from: dateStr) { return date.timeIntervalSince1970 }
        if let date = _isoFmt.date(from: dateStr) { return date.timeIntervalSince1970 }
        if let date = _iso8601Fmt.date(from: dateStr) { return date.timeIntervalSince1970 }
        if let date = _dayFirstFmt.date(from: dateStr) { return date.timeIntervalSince1970 }
        if let date = _abbrevMonthDayFmt.date(from: dateStr) { return date.timeIntervalSince1970 }
        if let date = _fullMonthDayFmt.date(from: dateStr) { return date.timeIntervalSince1970 }
        if let date = _monthYearFmt.date(from: dateStr) { return date.timeIntervalSince1970 }
        if let date = _abbrevMonthYearFmt.date(from: dateStr) { return date.timeIntervalSince1970 }
        return nil
    }
}
