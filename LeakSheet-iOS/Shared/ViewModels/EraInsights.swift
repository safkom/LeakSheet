import Foundation

/// The numbers and lists the era info sheet shows, derived from one era of a loaded artist.
/// Per-era work is a few hundred versions at most, so it runs on the main actor.
struct EraInsights {
    struct Count: Identifiable, Equatable {
        let label: String
        let value: Int
        var id: String { label }
    }

    struct DateRange: Equatable {
        /// The raw sheet strings of the earliest and latest parsed dates.
        let first: String
        let last: String
    }

    let songCount: Int
    let versionCount: Int
    let playableCount: Int
    let leakDates: DateRange?
    let fileDates: DateRange?
    /// Quality tiers in display order, empty tiers dropped.
    let quality: [(variant: BadgeVariant, count: Int)]
    let topProducers: [Count]
    let topFeatures: [Count]
    let sections: [Count]
    let miscEntries: [MiscEntry]
    let previousEra: String?
    let nextEra: String?

    static let qualityOrder: [BadgeVariant] = [.lossless, .og, .cd, .hq, .rec, .lq, .beatonly, .na]

    static func compute(era: Era, artist: Artist, topLimit: Int = 8) -> EraInsights {
        let versions = era.allSongs.flatMap(\.versions)

        var tiers: [BadgeVariant: Int] = [:]
        var producers: [String: (name: String, count: Int)] = [:]
        var features: [String: (name: String, count: Int)] = [:]
        for version in versions {
            tiers[qualityVariant(version.quality), default: 0] += 1
            for name in creditNames(version.producers) { tally(&producers, name) }
            for raw in [version.featuring, version.creditedArtists] {
                for name in creditNames(raw) { tally(&features, name) }
            }
        }

        let eraNames = artist.eras.map(\.name)
        let index = eraNames.firstIndex(of: era.name)
        let eraKey = ArtistViewModel.eraMatchKey(era.name)
        let misc = (artist.tabs ?? []).flatMap(\.entries).filter { ArtistViewModel.eraMatchKey($0.eraName) == eraKey }

        return EraInsights(
            songCount: era.computedSongCount,
            versionCount: versions.count,
            playableCount: versions.filter(\.isStreamable).count,
            leakDates: dateRange(versions.compactMap(\.leakDate)),
            fileDates: dateRange(versions.compactMap(\.fileDate)),
            quality: qualityOrder.compactMap { v in tiers[v].map { (v, $0) } },
            topProducers: top(producers, limit: topLimit),
            topFeatures: top(features, limit: topLimit),
            sections: (era.sections ?? []).filter { !$0.name.isEmpty }.map { Count(label: $0.name, value: $0.songs.count) },
            miscEntries: misc,
            previousEra: index.flatMap { $0 > 0 ? eraNames[$0 - 1] : nil },
            nextEra: index.flatMap { $0 + 1 < eraNames.count ? eraNames[$0 + 1] : nil }
        )
    }

    /// Earliest and latest of the dates that parse; unparseable strings are skipped.
    static func dateRange(_ raws: [String]) -> DateRange? {
        let parsed = raws.map { ($0, ArtistViewModel.parseLeakDate($0)) }.filter { $0.1 > 0 }
        guard let first = parsed.min(by: { $0.1 < $1.1 }), let last = parsed.max(by: { $0.1 < $1.1 }) else { return nil }
        return DateRange(first: first.0, last: last.0)
    }

    // shortcut: splits on "," and "&" only; swap in the credit-name splitter once it lands.
    static func creditNames(_ raw: String?) -> [String] {
        guard let raw, !raw.isEmpty else { return [] }
        return raw.split(whereSeparator: { $0 == "," || $0 == "&" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && $0 != "???" }
    }

    private static func tally(_ counts: inout [String: (name: String, count: Int)], _ name: String) {
        counts[name.lowercased(), default: (name, 0)].count += 1
    }

    private static func top(_ counts: [String: (name: String, count: Int)], limit: Int) -> [Count] {
        counts.values
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.name < $1.name }
            .prefix(limit)
            .map { Count(label: $0.name, value: $0.count) }
    }
}
