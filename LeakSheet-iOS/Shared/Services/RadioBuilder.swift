import Foundation

/// The playlists behind Era Radio, Credit Radio, Newest Leaks and Smart Shuffle, each
/// played with `playInList` so it stops at its own end (DECISIONS.md::RadioBuilder.swift::stations).
nonisolated enum RadioBuilder {
    static let newestLeaksCap = 50
    /// A smart shuffle suggests one version after every this-many favourites.
    static let suggestEvery = 3

    /// Each song's best playable version, shuffled. Songs with nothing playable drop out.
    static func eraRadio(
        era: FilteredEra, artistName: String, artistSlug: String,
        using rng: inout some RandomNumberGenerator
    ) -> [PlaybackListItem] {
        let items: [PlaybackListItem] = era.allSongs.compactMap { song in
            guard let version = song.bestPlayableVersion, version.isStreamable else { return nil }
            return makeItem(version, artistName, era.era.name, era.era.artUrl ?? "", artistSlug)
        }
        return items.shuffled(using: &rng)
    }

    /// A credit page's streamable versions, shuffled.
    static func creditRadio(
        versions: [CreditProfile.Credited], artistName: String, artistSlug: String,
        using rng: inout some RandomNumberGenerator
    ) -> [PlaybackListItem] {
        versions
            .filter { $0.version.isStreamable }
            .map { makeItem($0.version, artistName, $0.eraName, $0.eraArt ?? "", artistSlug) }
            .shuffled(using: &rng)
    }

    /// The artist's newest-leaked playable versions, newest first, capped.
    static func newestLeaks(artist: Artist) -> [PlaybackListItem] {
        var items: [PlaybackListItem] = []
        for result in ArtistViewModel.computeRecentResults(artist: artist, state: FilterState())
        where result.version.isStreamable {
            items.append(makeItem(result.version, artist.name, result.era.name,
                                  result.era.artUrl ?? "", artist.slug))
            if items.count == newestLeaksCap { break }
        }
        return items
    }

    /// Favourites shuffled, with one unheard playable version from the last favourite's era
    /// after every `suggestEvery`. Never repeats a favourite; adds none for an era with nothing unheard.
    static func smartShuffle(
        favourites: [PlaybackListItem],
        candidatesByEra: [String: [PlaybackListItem]],
        isHeard: (PlaybackListItem) -> Bool,
        using rng: inout some RandomNumberGenerator
    ) -> [PlaybackListItem] {
        var placed = Set(favourites.map(\.version))
        var station: [PlaybackListItem] = []
        for (index, favourite) in favourites.shuffled(using: &rng).enumerated() {
            station.append(favourite)
            guard (index + 1) % suggestEvery == 0 else { continue }
            let fresh = (candidatesByEra[eraKey(favourite)] ?? []).filter {
                $0.version.isStreamable && !placed.contains($0.version) && !isHeard($0)
            }
            guard var suggestion = fresh.randomElement(using: &rng) else { continue }
            placed.insert(suggestion.version)
            suggestion.isInserted = true
            station.append(suggestion)
        }
        return station
    }

    /// Streamable versions of every era of the given trackers, keyed by `eraKey`.
    static func candidatesByEra(artists: [Artist]) -> [String: [PlaybackListItem]] {
        var byEra: [String: [PlaybackListItem]] = [:]
        for artist in artists {
            for era in artist.eras {
                byEra[eraKey(artistSlug: artist.slug, eraName: era.name)] = era.allSongs
                    .flatMap(\.versions)
                    .filter(\.isStreamable)
                    .map { makeItem($0, artist.name, era.name, era.artUrl ?? "", artist.slug) }
            }
        }
        return byEra
    }

    static func eraKey(_ item: PlaybackListItem) -> String {
        eraKey(artistSlug: item.artistSlug ?? "", eraName: item.eraName)
    }

    static func eraKey(artistSlug: String, eraName: String) -> String {
        "\(artistSlug)::\(eraName)"
    }

    private static func makeItem(
        _ version: SongVersion, _ artistName: String, _ eraName: String,
        _ artUrl: String, _ artistSlug: String
    ) -> PlaybackListItem {
        PlaybackListItem(version: version, artistName: artistName, eraName: eraName,
                         artUrl: artUrl, artistSlug: artistSlug)
    }
}
