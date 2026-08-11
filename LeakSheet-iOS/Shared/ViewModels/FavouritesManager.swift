import Foundation
import Observation
import OSLog

/// Manages favourited songs with UserDefaults persistence.
/// Composite key: "artistSlug::eraName::baseName"
@MainActor
@Observable
final class FavouritesManager {
    static let shared = FavouritesManager()

    private static let storageKey = "leaksheet_favourites"
    private static let log = Logger(subsystem: "eu.safko.LeakSheet", category: "Favourites")

    var entries: [FavouriteEntry] = [] {
        didSet { keyIndex = Set(entries.map(\.key)) }
    }

    /// `entries` keys, for O(1) `isFavourited` during scroll.
    private var keyIndex: Set<String> = []

    nonisolated struct FavouriteEntry: Codable, Identifiable, Sendable {
        var id: String { key }
        let key: String
        let artistSlug: String
        let artistName: String
        let sourceUrl: String?
        let eraName: String
        let eraArt: String?
        let songBaseName: String
        let songVersionCount: Int
        let badge: String?
        let addedAt: Date
        // Full version snapshot — preserves featuring, producers, samples,
        // refs, etc. so the description sheet renders complete metadata.
        // Optional so entries persisted before this field existed still decode.
        let primaryVersion: SongVersion?
        // Legacy flat fields kept for backward compatibility with entries
        // written before `primaryVersion` was added. New writes leave them nil.
        let primaryVersionName: String?
        let primaryVersionTag: String?
        let links: [String]?
        let quality: String?
        let availableLength: String?
        let notes: String?
        let trackLength: String?
        let leakDate: String?

        /// Reconstruct a SongVersion for playback / description display.
        /// Prefers the full stored snapshot; falls back to the legacy flat
        /// fields for entries written before the snapshot field existed.
        var toSongVersion: SongVersion? {
            if let v = primaryVersion { return v }
            guard let name = primaryVersionName else { return nil }
            return SongVersion(
                name: name,
                versionTag: primaryVersionTag,
                badge: badge,
                featuring: nil,
                producers: nil,
                collaboration: nil,
                refs: nil,
                director: nil,
                creditedArtists: nil,
                altTitles: nil,
                notes: notes,
                ogFilename: nil,
                ogFilenames: nil,
                samples: nil,
                trackLength: trackLength,
                fileDate: nil,
                leakDate: leakDate,
                availableLength: availableLength,
                quality: quality,
                streaming: nil,
                links: links,
                dateOfRecording: nil,
                type: nil,
                sources: nil,
                rating: nil
            )
        }

        /// Copy with a new key/base name — see `migratingVersionTags`.
        func rekeyed(to newKey: String, baseName: String) -> FavouriteEntry {
            FavouriteEntry(
                key: newKey, artistSlug: artistSlug, artistName: artistName,
                sourceUrl: sourceUrl, eraName: eraName, eraArt: eraArt,
                songBaseName: baseName, songVersionCount: songVersionCount,
                badge: badge, addedAt: addedAt, primaryVersion: primaryVersion,
                primaryVersionName: primaryVersionName, primaryVersionTag: primaryVersionTag,
                links: links, quality: quality, availableLength: availableLength,
                notes: notes, trackLength: trackLength, leakDate: leakDate
            )
        }

        var toDescriptionPayload: SongDetailPayload? {
            guard let version = toSongVersion else { return nil }
            return SongDetailPayload(
                song: nil,
                version: version,
                artistName: artistName,
                artistSlug: artistSlug,
                eraName: eraName,
                eraArt: eraArt
            )
        }
    }

    private init() {
        load()
    }

    // MARK: - Key

    static func key(artistSlug: String, eraName: String, baseName: String) -> String {
        "\(artistSlug)::\(eraName)::\(baseName)"
    }

    // MARK: - Queries

    func isFavourited(artistSlug: String, eraName: String, baseName: String) -> Bool {
        // Set, not `entries.contains { }`: this runs once per visible row on
        // every scroll frame, against an array that grows with the library.
        keyIndex.contains(Self.key(artistSlug: artistSlug, eraName: eraName, baseName: baseName))
    }

    /// Check if a version is favourited by deriving its base name.
    func isFavouritedByVersion(_ version: SongVersion, artistSlug: String, eraName: String) -> Bool {
        isFavourited(artistSlug: artistSlug, eraName: eraName, baseName: version.derivedBaseName)
    }

    /// Group by artist → era, for global favourites panel. Use `groupedByArtist` for the cached version.
    func grouped() -> [(artistName: String, artistSlug: String, sourceUrl: String?, eras: [(eraName: String, eraArt: String?, entries: [FavouriteEntry])])] {
        groupedByArtist
    }

    // MARK: - Mutations

    @discardableResult
    func toggle(song: Song, artistSlug: String, artistName: String, sourceUrl: String?, eraName: String, eraArt: String?) -> Bool {
        let k = Self.key(artistSlug: artistSlug, eraName: eraName, baseName: song.baseName)
        if let idx = entries.firstIndex(where: { $0.key == k }) {
            entries.remove(at: idx)
            _groupedCache = nil
            save()
            return false
        } else {
            let primary = song.primary
            let entry = FavouriteEntry(
                key: k,
                artistSlug: artistSlug,
                artistName: artistName,
                sourceUrl: sourceUrl,
                eraName: eraName,
                eraArt: eraArt,
                songBaseName: song.baseName,
                songVersionCount: song.versions.count,
                badge: song.computedBadge?.rawValue,
                addedAt: Date(),
                primaryVersion: primary,
                primaryVersionName: nil,
                primaryVersionTag: nil,
                links: nil,
                quality: nil,
                availableLength: nil,
                notes: nil,
                trackLength: nil,
                leakDate: nil
            )
            entries.insert(entry, at: 0)
            _groupedCache = nil
            save()
            return true
        }
    }

    /// Toggle favourite from a single version (e.g. from description sheet or now playing).
    /// Derives `baseName` by stripping the version tag suffix from the version name.
    @discardableResult
    func toggleFromVersion(version: SongVersion, artistSlug: String, artistName: String, sourceUrl: String?, eraName: String, eraArt: String?) -> Bool {
        let baseName = version.derivedBaseName
        let k = Self.key(artistSlug: artistSlug, eraName: eraName, baseName: baseName)
        if let idx = entries.firstIndex(where: { $0.key == k }) {
            entries.remove(at: idx)
            _groupedCache = nil
            save()
            return false
        } else {
            let entry = FavouriteEntry(
                key: k,
                artistSlug: artistSlug,
                artistName: artistName,
                sourceUrl: sourceUrl,
                eraName: eraName,
                eraArt: eraArt,
                songBaseName: baseName,
                songVersionCount: 1,
                badge: version.badge,
                addedAt: Date(),
                primaryVersion: version,
                primaryVersionName: nil,
                primaryVersionTag: nil,
                links: nil,
                quality: nil,
                availableLength: nil,
                notes: nil,
                trackLength: nil,
                leakDate: nil
            )
            entries.insert(entry, at: 0)
            _groupedCache = nil
            save()
            return true
        }
    }

    func remove(key: String) {
        entries.removeAll { $0.key == key }
        _groupedCache = nil
        save()
    }

    func clearAll() {
        entries.removeAll()
        _groupedCache = nil
        save()
    }

    // MARK: - Grouped cache

    typealias GroupedArtist = (artistName: String, artistSlug: String, sourceUrl: String?, eras: [(eraName: String, eraArt: String?, entries: [FavouriteEntry])])

    @ObservationIgnored private var _groupedCache: [GroupedArtist]?

    var groupedByArtist: [GroupedArtist] {
        if let cached = _groupedCache { return cached }
        let result = Self.grouped(from: entries)
        _groupedCache = result
        return result
    }

    /// Group entries by artist → era with a DETERMINISTIC order: artists by
    /// their most recently added favourite (newest first), eras likewise,
    /// entries in stored order (newest first — inserts happen at index 0).
    /// Dictionary iteration order previously shuffled the favourites panel
    /// on every recompute.
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

    private func load() {
        // One-shot migration from UserDefaults
        if let legacyData = UserDefaults.standard.data(forKey: Self.storageKey),
           let migrated = try? JSONDecoder().decode([FavouriteEntry].self, from: legacyData) {
            entries = migrated
            save()
            UserDefaults.standard.removeObject(forKey: Self.storageKey)
            return
        }

        guard let data = try? Data(contentsOf: Self.storageFile) else { return }
        do {
            entries = Self.migratingVersionTags(try JSONDecoder().decode([FavouriteEntry].self, from: data))
        } catch {
            Self.log.error("Failed to decode favourites (\(data.count, privacy: .public) bytes): \(error.localizedDescription, privacy: .public)")
            entries = []
        }
    }

    /// Tags the backend started recognising in 2026-08. Entries saved before
    /// that carry them inside `songBaseName` ("90210 [Demo 8]"), while rows now
    /// report the stripped name — so the heart silently stopped matching. This
    /// is a one-shot rewrite, deliberately narrow: it lists exactly the tag
    /// families that changed, so a genuine bracketed title like "X [Mixtape]"
    /// is left alone.
    ///
    /// ponytail: delete this once no install predates the change.
    private static let orphanedTagRE = try? NSRegularExpression(
        pattern: #"\s*\[(?:Demo(?:\s+\d+)?|OG File|Master File|Instrumental|Rough Mix|Final(?:\s+Mix)?(?:\s+\d+)?|Remix|Mix [A-Z]|Live)\]\s*$"#,
        options: [.caseInsensitive]
    )

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
            // Another version of the same song is already favourited under the
            // stripped name — leave this one alone rather than create a
            // duplicate key.
            guard !seen.contains(newKey) else { return entry }
            seen.insert(newKey)
            return entry.rekeyed(to: newKey, baseName: stripped)
        }
    }

    private var saveTask: Task<Void, Never>?

    /// Persist off the main actor and coalesce bursts of toggles into one write.
    /// Previously this JSON-encoded the whole entries array (each embeds a full
    /// version snapshot) and did a synchronous atomic file write on the main
    /// actor on every heart tap — a per-tap hitch that scaled with library size.
    private func save() {
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
