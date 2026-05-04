import Foundation
import Observation

/// Manages recently viewed trackers with UserDefaults persistence. Cap: 20.
@MainActor
@Observable
final class RecentTrackersManager {
    static let shared = RecentTrackersManager()

    private static let storageKey = "leaksheet_recent_trackers"
    private static let maxEntries = 20

    var trackers: [RecentTracker] = []

    nonisolated struct RecentTracker: Codable, Identifiable, Sendable {
        var id: String { sourceUrl }
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

        trackers.removeAll { $0.sourceUrl == entry.sourceUrl }
        trackers.insert(entry, at: 0)
        if trackers.count > Self.maxEntries {
            trackers = Array(trackers.prefix(Self.maxEntries))
        }
        save()
    }

    func remove(sourceUrl: String) {
        trackers.removeAll { $0.sourceUrl == sourceUrl }
        save()
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
        trackers = (try? JSONDecoder().decode([RecentTracker].self, from: data)) ?? []
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(trackers) else { return }
        UserDefaults.standard.set(data, forKey: Self.storageKey)
    }
}
