import Foundation
import Observation
import OSLog

/// Manages favourited songs, persisted as a JSON file.
/// Composite key: "artistSlug::eraName::baseName"
@MainActor
@Observable
final class FavouritesManager {
    static let shared = FavouritesManager()

    static let storageKey = "leaksheet_favourites"
    static let log = Logger(subsystem: "si.safko.LeakSheet", category: "Favourites")

    var entries: [FavouriteEntry] = [] {
        didSet {
            keyIndex = Set(entries.map(\.key))
            // Invalidated here rather than at each mutation, so no write path can miss it.
            groupedCache = nil
        }
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
        // Full version snapshot, so the description sheet renders complete metadata.
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
            if let primary = primaryVersion { return primary }
            guard let name = primaryVersionName else { return nil }
            return SongVersion(
                name: name,
                versionTag: primaryVersionTag,
                badge: badge,
                notes: notes,
                trackLength: trackLength,
                leakDate: leakDate,
                availableLength: availableLength,
                quality: quality,
                links: links
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

    @ObservationIgnored var groupedCache: [GroupedArtist]?

    // MARK: - Key

    /// Favourite identity: artist + era + song name, lower-cased (the parser groups
    /// names that differ only in case).
    ///
    /// A placeholder name ("???") identifies nothing, so placeholders ALONE also carry
    /// the file link, the same discriminator the now-playing indicator uses.
    static func key(
        artistSlug: String, eraName: String, baseName: String,
        discriminator: String? = nil
    ) -> String {
        let base = "\(artistSlug)::\(eraName)::\(baseName)".lowercased()
        guard Song.isPlaceholderName(baseName),
              let discriminator, !discriminator.isEmpty
        else { return base }
        return "\(base)::\(discriminator)"
    }

    /// What tells two rows with the same placeholder name apart.
    static func discriminator(for version: SongVersion?) -> String? {
        version?.links?.first
    }

    // MARK: - Queries

    func isFavourited(
        artistSlug: String, eraName: String, baseName: String,
        discriminator: String? = nil
    ) -> Bool {
        // Set, not `entries.contains { }`: this runs once per visible row on
        // every scroll frame, against an array that grows with the library.
        keyIndex.contains(Self.key(
            artistSlug: artistSlug, eraName: eraName,
            baseName: baseName, discriminator: discriminator
        ))
    }

    /// Whether *song* is favourited — the row-level query. Carries the song so
    /// a placeholder title can be told apart from its namesakes.
    func isFavourited(song: Song, artistSlug: String, eraName: String) -> Bool {
        isFavourited(
            artistSlug: artistSlug, eraName: eraName, baseName: song.baseName,
            discriminator: Self.discriminator(for: song.primary)
        )
    }

    /// Check if a version is favourited by deriving its base name.
    func isFavouritedByVersion(_ version: SongVersion, artistSlug: String, eraName: String) -> Bool {
        isFavourited(
            artistSlug: artistSlug, eraName: eraName,
            baseName: version.derivedBaseName,
            discriminator: Self.discriminator(for: version)
        )
    }

    // MARK: - Mutations

    @discardableResult
    func toggle(
        song: Song,
        artistSlug: String,
        artistName: String,
        sourceUrl: String?,
        eraName: String,
        eraArt: String?
    ) -> Bool {
        toggleEntry(
            baseName: song.baseName,
            discriminator: Self.discriminator(for: song.primary),
            versionCount: song.versions.count,
            badge: song.computedBadge?.rawValue,
            // The version the row shows, not versions[0] — the saved entry
            // should look like what was hearted.
            primaryVersion: song.bestPlayableVersion ?? song.primary,
            artistSlug: artistSlug, artistName: artistName, sourceUrl: sourceUrl,
            eraName: eraName, eraArt: eraArt
        )
    }

    /// Toggle favourite from a single version (e.g. from description sheet or now playing).
    /// Derives `baseName` by stripping the version tag suffix from the version name.
    @discardableResult
    func toggleFromVersion(
        version: SongVersion,
        artistSlug: String,
        artistName: String,
        sourceUrl: String?,
        eraName: String,
        eraArt: String?
    ) -> Bool {
        toggleEntry(
            baseName: version.derivedBaseName,
            discriminator: Self.discriminator(for: version),
            versionCount: 1,
            badge: version.badge,
            primaryVersion: version,
            artistSlug: artistSlug, artistName: artistName, sourceUrl: sourceUrl,
            eraName: eraName, eraArt: eraArt
        )
    }

    /// The player and details sheet don't carry the tracker URL; Recents knows it by slug.
    nonisolated static func resolvedSourceUrl(
        _ given: String?, artistSlug: String, recents: [RecentTrackersManager.RecentTracker]
    ) -> String? {
        if let given, !given.isEmpty { return given }
        // Two trackers can share a slug (alt trackers); guessing would store the wrong one.
        let matches = recents.filter { $0.slug == artistSlug && !$0.sourceUrl.isEmpty }
        return matches.count == 1 ? matches[0].sourceUrl : nil
    }

    @discardableResult
    private func toggleEntry(
        baseName: String, discriminator: String?, versionCount: Int, badge: String?,
        primaryVersion: SongVersion?, artistSlug: String, artistName: String,
        sourceUrl: String?, eraName: String, eraArt: String?
    ) -> Bool {
        let entryKey = Self.key(
            artistSlug: artistSlug,
            eraName: eraName,
            baseName: baseName,
            discriminator: discriminator
        )
        if let idx = entries.firstIndex(where: { $0.key == entryKey }) {
            entries.remove(at: idx)
            save()
            return false
        } else {
            let entry = FavouriteEntry(
                key: entryKey,
                artistSlug: artistSlug,
                artistName: artistName,
                sourceUrl: Self.resolvedSourceUrl(
                    sourceUrl, artistSlug: artistSlug, recents: RecentTrackersManager.shared.trackers
                ),
                eraName: eraName,
                eraArt: eraArt,
                songBaseName: baseName,
                songVersionCount: versionCount,
                badge: badge,
                addedAt: Date(),
                primaryVersion: primaryVersion,
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
            save()
            return true
        }
    }

    func remove(key: String) {
        entries.removeAll { $0.key == key }
        save()
    }

    func clearAll() {
        entries.removeAll()
        save()
    }

    var saveTask: Task<Void, Never>?

}
