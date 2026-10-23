import Foundation
import Observation
import OSLog

/// Plays per song version and the recently played list, persisted as a JSON file.
/// Local only: nothing leaves the device.
@MainActor
@Observable
final class ListeningHistory {
    static let shared = ListeningHistory(fileURL: storageFile, defaults: .standard)

    static let enabledKey = "leaksheet_history_enabled"
    static let recentLimit = 30

    private static let log = Logger(subsystem: "si.safko.LeakSheet", category: "History")

    nonisolated struct Tally: Codable, Sendable, Equatable {
        var count: Int
        var last: Date
    }

    nonisolated struct RecentPlay: Codable, Identifiable, Sendable {
        /// artistSlug + version key: the same version under two artists is two rows.
        let id: String
        let artistSlug: String
        let artistName: String
        let eraName: String
        let eraArt: String?
        /// Full snapshot, so Landing can play it without loading the tracker.
        let version: SongVersion
        let last: Date
    }

    nonisolated struct Snapshot: Codable, Sendable {
        var plays: [String: [String: Tally]]
        var recent: [RecentPlay]
    }

    /// artistSlug → version key → tally.
    private(set) var plays: [String: [String: Tally]] = [:]
    /// Newest first, capped at `recentLimit`.
    private(set) var recent: [RecentPlay] = []

    @ObservationIgnored private let fileURL: URL
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var saveTask: Task<Void, Never>?

    /// Unset means on: history is recorded until the user switches it off.
    var isEnabled: Bool {
        defaults.object(forKey: Self.enabledKey) as? Bool ?? true
    }

    init(fileURL: URL, defaults: UserDefaults) {
        self.fileURL = fileURL
        self.defaults = defaults
        load()
    }

    // MARK: - Key

    /// Era, name and tag identify a version. A placeholder name also needs the file link,
    /// or two different "???" tracks in one era would share a row.
    static func versionKey(eraName: String, version: SongVersion) -> String {
        let name = version.derivedBaseName
        let base = "\(eraName)::\(Song.nameKey(name))::\(version.versionTag ?? "")".lowercased()
        guard Song.isPlaceholderName(name),
              let discriminator = FavouritesManager.discriminator(for: version),
              !discriminator.isEmpty
        else { return base }
        return "\(base)::\(discriminator)"
    }

    // MARK: - Queries

    /// Set lookup: runs once per visible row on every scroll frame.
    func isHeard(_ version: SongVersion, artistSlug: String, eraName: String) -> Bool {
        plays[artistSlug]?[Self.versionKey(eraName: eraName, version: version)] != nil
    }

    func entries(for artistSlug: String) -> [String: Tally] {
        plays[artistSlug] ?? [:]
    }

    // MARK: - Mutations

    /// Counts one play of *version*. Does nothing while history is switched off.
    func record(
        _ version: SongVersion, artistSlug: String, artistName: String,
        eraName: String, eraArt: String?, at date: Date = .now
    ) {
        guard isEnabled else { return }
        let key = Self.versionKey(eraName: eraName, version: version)

        var tally = plays[artistSlug]?[key] ?? Tally(count: 0, last: date)
        tally.count += 1
        tally.last = date
        plays[artistSlug, default: [:]][key] = tally

        let id = "\(artistSlug)::\(key)"
        recent.removeAll { $0.id == id }
        recent.insert(
            RecentPlay(
                id: id, artistSlug: artistSlug, artistName: artistName,
                eraName: eraName, eraArt: eraArt, version: version, last: date
            ),
            at: 0
        )
        if recent.count > Self.recentLimit {
            recent.removeLast(recent.count - Self.recentLimit)
        }
        save()
    }

    func clear() {
        plays = [:]
        recent = []
        save()
    }

    // MARK: - Persistence

    private static let storageFile: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("leaksheet", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("listening-history.json")
    }()

    private func load() {
        guard let data = try? Data(contentsOf: fileURL) else { return }
        do {
            let snapshot = try JSONDecoder().decode(Snapshot.self, from: data)
            plays = snapshot.plays
            recent = Array(snapshot.recent.prefix(Self.recentLimit))
        } catch {
            Self.log.error("Failed to decode listening history (\(data.count, privacy: .public) bytes): \(error.localizedDescription, privacy: .public)")
            // Keep the unreadable file, as favourites do: the next save would replace it.
            let aside = fileURL.deletingPathExtension().appendingPathExtension("unreadable.json")
            try? FileManager.default.removeItem(at: aside)
            try? FileManager.default.moveItem(at: fileURL, to: aside)
        }
    }

    /// Persist off the main actor and coalesce bursts of plays into one write.
    private func save() {
        let snapshot = Snapshot(plays: plays, recent: recent)
        let file = fileURL
        let logger = Self.log
        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(for: .milliseconds(150))
            if Task.isCancelled { return }
            await Self.persist(snapshot, to: file, logger: logger)
        }
    }

    /// Persist immediately (the app is backgrounding). Awaits the in-flight write
    /// rather than cancelling it, so an older snapshot cannot land last.
    func flush() async {
        let inFlight = saveTask
        saveTask = nil
        inFlight?.cancel()
        await inFlight?.value
        await Self.persist(Snapshot(plays: plays, recent: recent), to: fileURL, logger: Self.log)
    }

    // @concurrent keeps the JSON encode and write off the main actor, as in FavouritesManager.
    @concurrent
    private nonisolated static func persist(
        _ snapshot: Snapshot, to file: URL, logger: Logger
    ) async {
        do {
            let data = try JSONEncoder().encode(snapshot)
            try data.write(to: file, options: .atomic)
        } catch {
            logger.error("Failed to save listening history: \(error.localizedDescription, privacy: .public)")
        }
    }
}

// MARK: - Summaries

extension ListeningHistory {
    /// One era's listening, summed over its versions.
    struct EraListening: Equatable {
        /// Distinct versions played at least once.
        let heard: Int
        /// Versions in the era: the denominator for `heard`.
        let versions: Int
        let plays: Int
        let last: Date?
    }

    /// Takes one artist's tallies (`entries(for:)`), so each version is a single key lookup.
    static func eraListening(_ era: Era, entries: [String: Tally]) -> EraListening {
        let versions = era.allSongs.flatMap(\.versions)
        var heard = 0
        var plays = 0
        var last: Date?
        for version in versions {
            guard let tally = entries[versionKey(eraName: era.name, version: version)] else { continue }
            heard += 1
            plays += tally.count
            last = max(last ?? tally.last, tally.last)
        }
        return EraListening(heard: heard, versions: versions.count, plays: plays, last: last)
    }

    /// Eras with plays, most played first; ties sort by name. Eras never played are dropped.
    static func topEras(in artist: Artist, entries: [String: Tally], limit: Int = 5) -> [(name: String, plays: Int)] {
        artist.eras
            .map { (name: $0.name, plays: eraListening($0, entries: entries).plays) }
            .filter { $0.plays > 0 }
            .sorted { $0.plays != $1.plays ? $0.plays > $1.plays : $0.name < $1.name }
            .prefix(limit)
            .map { $0 }
    }
}

/// Whether a play counts as heard: 30 seconds listened, or half the track when its length is known.
/// Half only binds below 60 seconds, since 30 seconds comes first above that.
nonisolated enum PlayThreshold {
    static func reached(listened: TimeInterval, duration: TimeInterval) -> Bool {
        if listened >= 30 { return true }
        guard duration > 0 else { return false }
        return listened >= duration * 0.5
    }
}
