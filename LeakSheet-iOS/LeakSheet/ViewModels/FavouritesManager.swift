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

    var entries: [FavouriteEntry] = []

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
        // Version data (optional for backward compat)
        let primaryVersionName: String?
        let primaryVersionTag: String?
        let links: [String]?
        let quality: String?
        let availableLength: String?
        let notes: String?
        let trackLength: String?
        let leakDate: String?

        /// Reconstruct a SongVersion from stored fields for playback.
        var toSongVersion: SongVersion? {
            guard let name = primaryVersionName else { return nil }
            return SongVersion(
                name: name,
                versionTag: primaryVersionTag,
                badge: badge,
                featuring: nil,
                producers: nil,
                collaboration: nil,
                refs: nil,
                altTitles: nil,
                notes: notes,
                ogFilename: nil,
                samples: nil,
                trackLength: trackLength,
                fileDate: nil,
                leakDate: leakDate,
                availableLength: availableLength,
                quality: quality,
                links: links,
                qualityColor: nil,
                availableLengthColor: nil,
                dateOfRecording: nil,
                type: nil
            )
        }

        var toDescriptionPayload: DescriptionSheet.Payload? {
            guard let version = toSongVersion else { return nil }
            return DescriptionSheet.Payload(
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
        let k = Self.key(artistSlug: artistSlug, eraName: eraName, baseName: baseName)
        return entries.contains { $0.key == k }
    }

    /// Check if a version is favourited by deriving its base name.
    func isFavouritedByVersion(_ version: SongVersion, artistSlug: String, eraName: String) -> Bool {
        var baseName = version.name
        if let tag = version.versionTag, baseName.hasSuffix(" [\(tag)]") {
            baseName = String(baseName.dropLast(tag.count + 3))
        }
        return isFavourited(artistSlug: artistSlug, eraName: eraName, baseName: baseName)
    }

    func favouritesForArtist(_ slug: String) -> [FavouriteEntry] {
        entries.filter { $0.artistSlug == slug }
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
                primaryVersionName: primary?.name,
                primaryVersionTag: primary?.versionTag,
                links: primary?.links,
                quality: primary?.quality,
                availableLength: primary?.availableLength,
                notes: primary?.notes,
                trackLength: primary?.trackLength,
                leakDate: primary?.leakDate
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
        // Derive base name by stripping trailing " [Vx]" tag
        var baseName = version.name
        if let tag = version.versionTag, baseName.hasSuffix(" [\(tag)]") {
            baseName = String(baseName.dropLast(tag.count + 3))
        }

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
                primaryVersionName: version.name,
                primaryVersionTag: version.versionTag,
                links: version.links,
                quality: version.quality,
                availableLength: version.availableLength,
                notes: version.notes,
                trackLength: version.trackLength,
                leakDate: version.leakDate
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
        let result = computeGrouped()
        _groupedCache = result
        return result
    }

    private func computeGrouped() -> [GroupedArtist] {
        var artistMap: [String: (name: String, slug: String, url: String?, eras: [String: (art: String?, entries: [FavouriteEntry])])] = [:]
        for entry in entries {
            if artistMap[entry.artistSlug] == nil {
                artistMap[entry.artistSlug] = (entry.artistName, entry.artistSlug, entry.sourceUrl, [:])
            }
            if var artistEntry = artistMap[entry.artistSlug] {
                if artistEntry.eras[entry.eraName] == nil {
                    artistEntry.eras[entry.eraName] = (entry.eraArt, [])
                }
                artistEntry.eras[entry.eraName]!.entries.append(entry)
                artistMap[entry.artistSlug] = artistEntry
            }
        }
        return artistMap.values.map { a in
            let eras = a.eras.map { (eraName: $0.key, eraArt: $0.value.art, entries: $0.value.entries) }
            return (artistName: a.name, artistSlug: a.slug, sourceUrl: a.url, eras: eras)
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
            entries = try JSONDecoder().decode([FavouriteEntry].self, from: data)
        } catch {
            Self.log.error("Failed to decode favourites (\(data.count, privacy: .public) bytes): \(error.localizedDescription, privacy: .public)")
            entries = []
        }
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(entries) else { return }
        try? data.write(to: Self.storageFile, options: .atomic)
    }
}
