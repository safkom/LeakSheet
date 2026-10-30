import Foundation
import SwiftUI
import Observation

extension ArtistViewModel {
    // MARK: - Nested types

    /// One era containing another copy of a song (matched by `songKey`).
    nonisolated struct CrossEraRef: Equatable, Sendable, Identifiable {
        let eraName: String
        let eraArt: String?
        let song: Song
        var id: String { eraName }
    }

    /// One playable version of a cross-era song, with the era it belongs to —
    /// what the description sheet's version picker lists and switches between.
    nonisolated struct CrossEraVersion: Identifiable, Sendable {
        let version: SongVersion
        let song: Song?
        let eraName: String
        let eraArt: String?
        var id: String { "\(eraName)::\(version.id)" }
    }

    /// Position of one version in `artist.eras[era].sections[section].songs[song].versions[version]`.
    nonisolated struct CreditHit: Hashable, Sendable {
        let era: Int
        let section: Int
        let song: Int
        let version: Int
    }

    nonisolated enum CreditRole: Hashable, Sendable {
        case producer, feature
    }

    /// The heavy startup pass (era stats + the unfiltered content tree), computed
    /// off-main by `make(artist:)` so pushing a huge tracker doesn't hitch navigation.
    /// The song and credit maps one pass over the tracker builds for `Precomputed`.
    nonisolated struct TrackerIndex {
        var creditIndex: [CreditRole: [String: [CreditHit]]] = [:]
        var spellings: [String: [String: Int]] = [:]
        var keyEras: [String: [CrossEraRef]] = [:]
        var byBaseName: [String: [CrossEraRef]] = [:]
        var byTitleKey: [String: [CrossEraRef]] = [:]
        var byAltTitleKey: [String: [CrossEraRef]] = [:]

        /// Same order as `era.allSongs`, which flattens the sections.
        mutating func add(_ era: Era, at ei: Int) {
            for (si, section) in (era.sections ?? []).enumerated() {
                for (sj, song) in section.songs.enumerated() {
                    for (vi, version) in song.versions.enumerated() {
                        Precomputed.indexCredits(
                            version, at: CreditHit(era: ei, section: si, song: sj, version: vi),
                            into: &creditIndex, spellings: &spellings
                        )
                    }
                    add(song, in: era)
                }
            }
        }

        private mutating func add(_ song: Song, in era: Era) {
            // Before the placeholder guard: a "???" row's alt title is its only identity and
            // still links to the named song (never BY the placeholder title).
            let ref = CrossEraRef(eraName: era.name, eraArt: era.artUrl, song: song)
            for key in song.titleKeys { byTitleKey[key, default: []].append(ref) }
            for key in song.altTitleKeys { byAltTitleKey[key, default: []].append(ref) }
            // A placeholder title identifies nothing: indexing it would group every
            // unidentified track under one key. Mirrors the backend's empty songKey.
            guard !song.isPlaceholder else { return }
            byBaseName[song.baseName, default: []].append(ref)
            // One ref per era per key (a song appears once per era)
            guard let key = song.songKey, !key.isEmpty, keyEras[key]?.last?.eraName != era.name else { return }
            keyEras[key, default: []].append(ref)
        }
    }

    nonisolated struct Precomputed: Sendable {
        let eraStatsByName: [String: Stats]
        let artistStats: Stats
        /// TabSection.id → that tab's own totals, so the stats bar can describe
        /// whatever list is actually on screen.
        let tabStatsByKey: [String: Stats]
        let content: FilteredContent
        /// songKey → every era containing that song, in era order — backs
        /// the description sheet's "Also in" cross-era section.
        let songKeyEras: [String: [CrossEraRef]]
        /// baseName → every era containing it. The songKey-less fallback for
        /// both `resolvedSong` and `crossEraRefs`, so neither has to rescan
        /// the tracker (Era.allSongs rebuilds its array on each access).
        let baseNameEras: [String: [CrossEraRef]]
        /// Name key (Song.nameKey) → every song with that title, or that name
        /// as one part of a slash title; and → every song listing it as an alt
        /// title. Back `linkedRefs`, the picker's "Also Known As" row.
        let titleKeySongs: [String: [CrossEraRef]]
        let altTitleKeySongs: [String: [CrossEraRef]]
        let eraOrder: [String: Int]
        /// Per-era, per-song lowercased search haystack, built once off-main so each
        /// keystroke only compares. Shape mirrors `artist.eras[i].allSongs[j]`.
        let searchIndex: [[SongSearchFields]]
        /// Ordered playback contexts, one per era — what drives auto-advance into the
        /// next era. Built once off-main: it parses every version's link.
        let eraPlaybackContexts: [EraSongContext]
        /// Role → CreditNames.key → every version crediting that name.
        let creditIndex: [CreditRole: [String: [CreditHit]]]
        /// CreditNames.key → the most common spelling of that name.
        let creditDisplayNames: [String: String]

        /// Adds one version's producer and feature names to the credit index.
        static func indexCredits(
            _ version: SongVersion, at hit: CreditHit,
            into index: inout [CreditRole: [String: [CreditHit]]],
            spellings: inout [String: [String: Int]]
        ) {
            let roles: [(CreditRole, [String?])] = [
                (.producer, [version.producers]),
                (.feature, [version.featuring, version.creditedArtists, version.collaboration]),
            ]
            for (role, fields) in roles {
                var keys = Set<String>()
                for field in fields {
                    for name in CreditNames.split(field) {
                        let key = CreditNames.key(name)
                        // A punctuation-only name keys to "", which would pool unrelated credits.
                        guard !key.isEmpty else { continue }
                        keys.insert(key)
                        spellings[key, default: [:]][name, default: 0] += 1
                    }
                }
                for key in keys {
                    index[role, default: [:]][key, default: []].append(hit)
                }
            }
        }

        init(artist: Artist) {
            var index = TrackerIndex()
            var statsByName: [String: Stats] = [:]
            var eraStats: [Stats] = []
            for (ei, era) in artist.eras.enumerated() {
                let stats = ArtistViewModel.computeEraStats(era)
                statsByName[era.name] = stats
                eraStats.append(stats)
                index.add(era, at: ei)
            }
            let total = eraStats.reduce(0) { $0 + $1.total }
            let available = eraStats.reduce(0) { $0 + $1.available }
            let snippets = eraStats.reduce(0) { $0 + $1.snippets }
            let confirmed = eraStats.reduce(0) { $0 + $1.confirmed }
            let fullHQ = eraStats.reduce(0) { $0 + $1.fullHQ }
            self.creditIndex = index.creditIndex
            self.creditDisplayNames = index.spellings.mapValues { counts in
                // Most common spelling; the alphabetically first one wins a tie.
                counts.max { a, b in a.value != b.value ? a.value < b.value : a.key > b.key }?.key ?? ""
            }
            self.eraStatsByName = statsByName
            var tabStats: [String: Stats] = [:]
            for tab in artist.tabs ?? [] {
                tabStats[tab.id] = ArtistViewModel.computeTabStats(tab.entries)
            }
            self.tabStatsByKey = tabStats
            self.artistStats = Stats(
                total: total, available: available, snippets: snippets,
                confirmed: confirmed, fullHQ: fullHQ
            )
            self.content = ArtistViewModel.computeContent(
                artist: artist, state: FilterState(), eraStats: statsByName
            )
            // Only keys that actually span content are worth keeping
            self.songKeyEras = index.keyEras.filter { $0.value.count > 1 }
            self.baseNameEras = index.byBaseName
            self.titleKeySongs = index.byTitleKey
            self.altTitleKeySongs = index.byAltTitleKey
            self.eraOrder = Dictionary(
                artist.eras.enumerated().map { ($1.name, $0) }, uniquingKeysWith: { first, _ in first }
            )
            self.searchIndex = artist.eras.map { $0.allSongs.map(SongSearchFields.init(song:)) }
            self.eraPlaybackContexts = Self.playbackContexts(artist)
        }

        /// One playback context per era: its streamable versions in list order.
        static func playbackContexts(_ artist: Artist) -> [EraSongContext] {
            artist.eras.map { era in
                EraSongContext(
                    eraName: era.name,
                    artistName: artist.name,
                    artUrl: era.artUrl ?? "",
                    versions: era.allSongs.flatMap(\.versions).filter(\.isStreamable),
                    artistSlug: artist.slug
                )
            }
        }
    }

    // MARK: - Song lookup

    /// Resolve the full, unfiltered song for a description payload — the row
    /// that opened the sheet may be a single-version snapshot from the
    /// current filter.
    func resolvedSong(for payload: SongDetailPayload) -> Song? {
        let refs = crossEraRefs(for: payload)
        return refs.first(where: { $0.eraName == payload.eraName })?.song
            ?? refs.first?.song
            ?? payload.song
    }

    /// Every era containing this payload's song. Prefers `songKey` (only songs
    /// spanning >1 era), falling back to the base-name index, which covers the rest.
    ///
    /// A nil `payload.song` (Now Playing, Favourites) still resolves via the
    /// version's `derivedBaseName`, the key the base-name index is built on.
    func crossEraRefs(for payload: SongDetailPayload) -> [CrossEraRef] {
        if let payloadSong = payload.song {
            if let key = payloadSong.songKey, !key.isEmpty, let refs = songKeyEras[key] {
                return refs
            }
            guard !payloadSong.isPlaceholder else { return [] }
            return baseNameEras[payloadSong.baseName] ?? []
        }
        let derived = payload.version.derivedBaseName
        guard !Song.isPlaceholderName(derived) else { return [] }
        return baseNameEras[derived] ?? []
    }

    /// Songs linked to this payload's song by name, one hop: a song whose title is one
    /// of this song's names (title, slash-title part, alt title), or one listing this
    /// song's title as an alt title. Linked, never merged; excludes the song's own eras.
    /// See docs/decisions.md::parser.py::_reconcile_title_misreads.
    func linkedRefs(for payload: SongDetailPayload) -> [CrossEraRef] {
        let family = crossEraRefs(for: payload)
        let ownSongs = family.isEmpty ? payload.song.map { [$0] } ?? [] : family.map(\.song)
        var titles: Set<String> = []
        var names: Set<String> = []
        if ownSongs.isEmpty {
            // A bare version (Now Playing, Favourites): its own name and aliases.
            if !Song.isPlaceholderName(payload.version.derivedBaseName) {
                titles = Song.nameKeys(ofTitle: payload.version.derivedBaseName)
            }
            names = titles
            for alt in payload.version.altTitles ?? [] {
                names.formUnion(Song.nameKeys(ofTitle: alt))
            }
        } else {
            for song in ownSongs {
                titles.formUnion(song.titleKeys)
                names.formUnion(song.titleKeys)
                names.formUnion(song.altTitleKeys)
            }
        }

        func identity(_ ref: CrossEraRef) -> String {
            "\(ref.eraName)::\(ref.song.baseName)::\(ref.song.allVersions.first?.id ?? "")"
        }
        var seen = Set(family.map(identity))
        if let own = payload.song {
            seen.insert(identity(CrossEraRef(eraName: payload.eraName, eraArt: payload.eraArt, song: own)))
        }
        var linked: [CrossEraRef] = []
        for key in names {
            for ref in titleKeySongs[key] ?? [] where seen.insert(identity(ref)).inserted {
                linked.append(ref)
            }
        }
        for key in titles {
            for ref in altTitleKeySongs[key] ?? [] where seen.insert(identity(ref)).inserted {
                linked.append(ref)
            }
        }
        // Set iteration order is random; era order, then title, is stable.
        linked.sort {
            let (a, b) = (eraOrder[$0.eraName] ?? .max, eraOrder[$1.eraName] ?? .max)
            return a != b ? a < b : $0.song.baseName < $1.song.baseName
        }
        // ponytail: cap the row rather than rank; a generic alias ("Intro") names dozens of songs.
        return Array(linked.prefix(Self.maxLinkedSongs))
    }

    nonisolated static let maxLinkedSongs = 24
}
