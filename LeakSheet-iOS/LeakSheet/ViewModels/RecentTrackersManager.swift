import Foundation
import Observation

/// Manages recently viewed trackers with UserDefaults persistence. Cap: 20.
@MainActor
@Observable
final class RecentTrackersManager {
    static let shared = RecentTrackersManager()

    private static let storageKey = "leaksheet_recent_trackers"
    private nonisolated static let maxEntries = 20

    var trackers: [RecentTracker] = []

    nonisolated struct RecentTracker: Codable, Identifiable, Sendable {
        // Identity is the normalized tracker URL so URL variants of the same
        // tracker (edit vs htmlview, gid fragments, share params) collapse to
        // one entry. Entries without a URL fall back to the artist slug.
        var id: String { RecentTrackersManager.identityKey(sourceUrl: sourceUrl, slug: slug) }
        let name: String
        let slug: String
        let sourceUrl: String
        let totalSongs: Int
        /// Total playable versions across the tracker — this is what the
        /// artist header's "N tracks" subtitle counts, so the card shows the
        /// same number under the same "tracks" label instead of a
        /// same-looking-but-different song count (see U-4).
        let totalVersions: Int
        let artUrl: String?
        let availableCount: Int
        let snippetCount: Int
        let confirmedCount: Int

        init(
            name: String, slug: String, sourceUrl: String,
            totalSongs: Int, totalVersions: Int? = nil, artUrl: String?,
            availableCount: Int, snippetCount: Int, confirmedCount: Int
        ) {
            self.name = name
            self.slug = slug
            self.sourceUrl = sourceUrl
            self.totalSongs = totalSongs
            // Defaults to the song count when a caller (e.g. older code paths
            // or tests) doesn't distinguish versions from songs.
            self.totalVersions = totalVersions ?? totalSongs
            self.artUrl = artUrl
            self.availableCount = availableCount
            self.snippetCount = snippetCount
            self.confirmedCount = confirmedCount
        }

        // Backward-compatible decode — see DECISIONS.md::RecentTrackersManager.swift::totalVersions-decode
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            name = try c.decode(String.self, forKey: .name)
            slug = try c.decode(String.self, forKey: .slug)
            sourceUrl = try c.decode(String.self, forKey: .sourceUrl)
            totalSongs = try c.decode(Int.self, forKey: .totalSongs)
            totalVersions = try c.decodeIfPresent(Int.self, forKey: .totalVersions) ?? totalSongs
            artUrl = try c.decodeIfPresent(String.self, forKey: .artUrl)
            availableCount = try c.decode(Int.self, forKey: .availableCount)
            snippetCount = try c.decode(Int.self, forKey: .snippetCount)
            confirmedCount = try c.decode(Int.self, forKey: .confirmedCount)
        }
    }

    private init() {
        load()
    }

    // MARK: - Mutations

    func saveTracker(artist: Artist) {
        let artUrl = artist.eras.first(where: { $0.artUrl != nil })?.artUrl
        let stats = Self.computeStats(eras: artist.eras)

        let entry = RecentTracker(
            name: artist.name,
            slug: artist.slug,
            sourceUrl: artist.sourceUrl ?? "",
            totalSongs: artist.computedTotalSongs,
            totalVersions: artist.computedTotalVersions,
            artUrl: artUrl,
            availableCount: stats.available,
            snippetCount: stats.snippets,
            confirmedCount: stats.confirmed
        )

        trackers.removeAll { $0.id == entry.id }
        trackers.insert(entry, at: 0)
        if trackers.count > Self.maxEntries {
            trackers = Array(trackers.prefix(Self.maxEntries))
        }
        save()
    }

    // MARK: - Identity & dedup

    nonisolated static func identityKey(sourceUrl: String, slug: String) -> String {
        let trimmed = sourceUrl.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "slug:\(slug)" }
        return TrackerURLNormalizer.normalize(trimmed)
    }

    /// Keeps the first occurrence per identity key (the list is newest-first,
    /// so first = most recent) and enforces the entry cap.
    nonisolated static func deduplicated(
        _ entries: [RecentTracker], cap: Int = RecentTrackersManager.maxEntries
    ) -> [RecentTracker] {
        var seen = Set<String>()
        var result: [RecentTracker] = []
        for entry in entries {
            guard seen.insert(entry.id).inserted else { continue }
            result.append(entry)
            if result.count == cap { break }
        }
        return result
    }

    func clearAll() {
        trackers.removeAll()
        UserDefaults.standard.removeObject(forKey: Self.storageKey)
    }

    // MARK: - Stats helper

    private static func computeStats(eras: [Era]) -> (available: Int, snippets: Int, confirmed: Int) {
        // Delegates to single source of truth — see DECISIONS.md::RecentTrackersManager.swift::stats-source
        var available = 0, snippets = 0, confirmed = 0
        for era in eras {
            let s = ArtistViewModel.computeEraStats(era)
            available += s.available
            snippets += s.snippets
            confirmed += s.confirmed
        }
        return (available, snippets, confirmed)
    }

    // MARK: - Persistence

    private func load() {
        guard let data = UserDefaults.standard.data(forKey: Self.storageKey) else { return }
        let decoded = (try? JSONDecoder().decode([RecentTracker].self, from: data)) ?? []
        // One-time migration: collapse duplicates persisted before identity
        // moved to the normalized URL. Must happen before first render so
        // ForEach ids stay unique.
        trackers = Self.deduplicated(decoded)
        if trackers.count != decoded.count {
            save()
        }
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(trackers) else { return }
        UserDefaults.standard.set(data, forKey: Self.storageKey)
    }
}
