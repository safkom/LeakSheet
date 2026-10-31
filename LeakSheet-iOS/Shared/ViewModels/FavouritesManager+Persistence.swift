import Foundation
import Observation
import OSLog

extension FavouritesManager {
    // MARK: - Grouped cache

    typealias GroupedArtist = (
        artistName: String,
        artistSlug: String,
        sourceUrl: String?,
        eras: [(eraName: String, eraArt: String?, entries: [FavouriteEntry])]
    )

    var groupedByArtist: [GroupedArtist] {
        // Read `entries` before the cache check: the cache is @ObservationIgnored, so a hit
        // that never touched `entries` would leave the reading view subscribed to nothing.
        let current = entries
        if let cached = _groupedCache { return cached }
        let result = Self.grouped(from: current)
        _groupedCache = result
        return result
    }

    /// Group entries by artist → era with a DETERMINISTIC order: artists and eras by
    /// their most recently added favourite, entries in stored order (newest first).
    static func grouped(from entries: [FavouriteEntry]) -> [GroupedArtist] {
        struct EraBucket {
            let art: String?
            var entries: [FavouriteEntry] = []
            var newest: Date = .distantPast
        }
        struct ArtistBucket {
            let name: String
            let slug: String
            let url: String?
            var eraOrder: [String] = []
            var eras: [String: EraBucket] = [:]
            var newest: Date = .distantPast
        }

        var order: [String] = []
        var buckets: [String: ArtistBucket] = [:]
        for entry in entries {
            if buckets[entry.artistSlug] == nil {
                buckets[entry.artistSlug] = ArtistBucket(
                    name: entry.artistName, slug: entry.artistSlug, url: entry.sourceUrl
                )
                order.append(entry.artistSlug)
            }
            guard var artist = buckets[entry.artistSlug] else { continue }
            var era = artist.eras[entry.eraName] ?? {
                artist.eraOrder.append(entry.eraName)
                return EraBucket(art: entry.eraArt)
            }()
            era.entries.append(entry)
            era.newest = max(era.newest, entry.addedAt)
            artist.eras[entry.eraName] = era
            artist.newest = max(artist.newest, entry.addedAt)
            buckets[entry.artistSlug] = artist
        }

        return order
            .compactMap { buckets[$0] }
            .sorted { $0.newest > $1.newest }
            .map { artist in
                let eras = artist.eraOrder
                    .compactMap { name in artist.eras[name].map { (name, $0) } }
                    .sorted { $0.1.newest > $1.1.newest }
                    .map { (eraName: $0.0, eraArt: $0.1.art, entries: $0.1.entries) }
                return (artistName: artist.name, artistSlug: artist.slug, sourceUrl: artist.url, eras: eras)
            }
    }

    // MARK: - Persistence (file-backed JSON at Library/Application Support/leaksheet/)

    private static let appSupportDir: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("leaksheet", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    private static let storageFile: URL = appSupportDir.appendingPathComponent("favourites.json")

    func load() {
        // One-shot migration from UserDefaults
        if let legacyData = UserDefaults.standard.data(forKey: Self.storageKey),
           let migrated = try? JSONDecoder().decode([FavouriteEntry].self, from: legacyData) {
            // Migrate here too: this branch returns early, and holds the oldest keys.
            entries = Self.migratingKeyCase(Self.migratingPlaceholderKeys(Self.migratingVersionTags(migrated)))
            // Written synchronously, and the old copy removed only once the new one exists,
            // so there is never a moment with neither.
            if let data = try? JSONEncoder().encode(entries),
               (try? data.write(to: Self.storageFile, options: .atomic)) != nil {
                UserDefaults.standard.removeObject(forKey: Self.storageKey)
            }
            return
        }

        guard let data = try? Data(contentsOf: Self.storageFile) else { return }
        do {
            let stored = try JSONDecoder().decode([FavouriteEntry].self, from: data)
            let migrated = Self.migratingKeyCase(Self.migratingPlaceholderKeys(Self.migratingVersionTags(stored)))
            entries = migrated
            // Persist the rewrite, or it re-runs on every launch forever.
            if migrated.map(\.key) != stored.map(\.key) { save() }
        } catch {
            Self.log.error("""
                Failed to decode favourites (\(data.count, privacy: .public) bytes): \
                \(error.localizedDescription, privacy: .public)
                """)
            // Keep the unreadable file: the next save would otherwise replace
            // every favourite with whatever the user hearts next.
            let aside = Self.storageFile.deletingPathExtension().appendingPathExtension("unreadable.json")
            try? FileManager.default.removeItem(at: aside)
            try? FileManager.default.moveItem(at: Self.storageFile, to: aside)
            entries = []
        }
    }

    /// Lower-cases the name part of keys saved before `key` did.
    static func migratingKeyCase(_ stored: [FavouriteEntry]) -> [FavouriteEntry] {
        var seen = Set<String>()
        return stored.compactMap { entry in
            let parts = entry.key.components(separatedBy: "::")
            let newKey = (parts.prefix(3).map { $0.lowercased() } + parts.dropFirst(3)).joined(separator: "::")
            // Two entries that differed only in case are one favourite now.
            guard seen.insert(newKey).inserted else { return nil }
            return newKey == entry.key ? entry : entry.rekeyed(to: newKey, baseName: entry.songBaseName)
        }
    }

    /// Version-tag families the backend recognises now but did not always: older
    /// entries carry them in `songBaseName` ("90210 [Demo 8]") and stopped matching.
    /// Narrow on purpose, so a genuine bracketed title like "X [Mixtape]" is left alone.
    ///
    /// ponytail: delete once no install predates the backend change.
    private static let orphanedTagRE = try? NSRegularExpression(
        pattern: #"\s*\[(?:Demo(?:\s+\d+)?|OG File|Master File|Instrumental|Rough Mix|"#
            + #"Final(?:\s+Mix)?(?:\s+\d+)?|Remix|Mix [A-Z]|Live)\]\s*$"#,
        options: [.caseInsensitive]
    )

    /// Re-key placeholder favourites onto their file. Old "???" keys collide across an
    /// era, so each takes its stored version's link; one without a link keeps its key.
    static func migratingPlaceholderKeys(_ stored: [FavouriteEntry]) -> [FavouriteEntry] {
        var seen = Set(stored.map(\.key))
        return stored.map { entry in
            guard Song.isPlaceholderName(entry.songBaseName),
                  let discriminator = discriminator(for: entry.primaryVersion)
            else { return entry }
            let newKey = key(
                artistSlug: entry.artistSlug, eraName: entry.eraName,
                baseName: entry.songBaseName, discriminator: discriminator
            )
            guard newKey != entry.key, !seen.contains(newKey) else { return entry }
            seen.insert(newKey)
            return entry.rekeyed(to: newKey, baseName: entry.songBaseName)
        }
    }

    static func migratingVersionTags(_ stored: [FavouriteEntry]) -> [FavouriteEntry] {
        guard let regex = orphanedTagRE else { return stored }
        var seen = Set(stored.map(\.key))
        return stored.map { entry in
            let name = entry.songBaseName
            let range = NSRange(name.startIndex..., in: name)
            guard let match = regex.firstMatch(in: name, range: range), match.range.location > 0,
                  let swiftRange = Range(match.range, in: name)
            else { return entry }
            let stripped = String(name[name.startIndex..<swiftRange.lowerBound])
            let newKey = key(artistSlug: entry.artistSlug, eraName: entry.eraName, baseName: stripped)
            // Another version of the same song is already favourited under the stripped
            // name: leave this one alone rather than create a duplicate key.
            guard !seen.contains(newKey) else { return entry }
            seen.insert(newKey)
            return entry.rekeyed(to: newKey, baseName: stripped)
        }
    }

    /// Persist off the main actor and coalesce bursts of toggles into one write.
    func save() {
        let snapshot = entries              // Sendable value snapshot
        let file = Self.storageFile
        let logger = Self.log
        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(for: .milliseconds(150))
            if Task.isCancelled { return }
            await Self.persist(snapshot, to: file, logger: logger)
        }
    }

    /// Persist immediately, skipping the debounce (the app is backgrounding).
    ///
    /// Awaits the in-flight task rather than cancelling it: once `persist` is running
    /// it checks no cancellation, so a second writer could land an OLDER snapshot last.
    func flush() async {
        let inFlight = saveTask
        saveTask = nil
        inFlight?.cancel()
        await inFlight?.value
        await Self.persist(entries, to: Self.storageFile, logger: Self.log)
    }

    // @concurrent required — see DECISIONS.md::FavouritesManager.swift::concurrent-persist
    @concurrent
    private nonisolated static func persist(
        _ entries: [FavouriteEntry], to file: URL, logger: Logger
    ) async {
        do {
            let data = try JSONEncoder().encode(entries)
            try data.write(to: file, options: .atomic)
        } catch {
            logger.error("Failed to save favourites: \(error.localizedDescription, privacy: .public)")
        }
    }
}
