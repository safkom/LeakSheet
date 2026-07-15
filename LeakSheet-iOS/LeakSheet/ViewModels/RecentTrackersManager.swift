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
        let artUrl: String?
        let availableCount: Int
        let snippetCount: Int
        let confirmedCount: Int
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

    /// Removes the entry with the given identity (`RecentTracker.id`) —
    /// matching on `id` directly, rather than recomputing a normalized key
    /// from a raw sourceUrl, keeps this in lockstep with `saveTracker` and
    /// `deduplicated`, which both key on `id` too.
    func remove(id: String) {
        trackers.removeAll { $0.id == id }
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
        var available = 0, snippets = 0, confirmed = 0
        for era in eras {
            for song in era.allSongs {
                for v in song.versions {
                    if v.isStreamable { available += 1 }
                    let al = (v.availableLength ?? "").lowercased()
                    if al.contains("snippet") { snippets += 1 }
                    if al.contains("confirmed") { confirmed += 1 }
                }
            }
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
