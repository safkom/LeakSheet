import Foundation

/// One credited name in one role: what a credit page opens for. Lives here, not with the
/// views, because the tvOS target compiles the view-model code only.
struct CreditRef: Hashable, Identifiable {
    let key: String
    let role: ArtistViewModel.CreditRole
    var id: Self { self }
}

/// What one producer or featured artist worked on, derived from the loaded tracker.
/// Main-actor like the other insight types: a tracker holds a few thousand versions at most.
struct CreditProfile {
    /// One credited version and where it sits in the tracker.
    struct Credited: Identifiable {
        let eraName: String
        let eraArt: String?
        let song: Song
        let version: SongVersion
        let hit: ArtistViewModel.CreditHit
        var id: ArtistViewModel.CreditHit { hit }
    }

    struct Collaborator: Identifiable {
        let name: String
        /// Opens the collaborator's own page, in the role they are credited in more often.
        let ref: CreditRef
        let sharedVersions: Int
        var id: CreditRef { ref }
    }

    typealias Index = [ArtistViewModel.CreditRole: [String: [ArtistViewModel.CreditHit]]]

    let name: String
    let role: ArtistViewModel.CreditRole
    /// Hits in the other role, 0 when that role has no page for this name.
    let otherRoleCount: Int
    let songCount: Int
    let versionCount: Int
    let playableCount: Int
    let firstEra: String
    let lastEra: String
    let bestOf: [Credited]
    let topEras: [EraInsights.Count]
    let quality: [(variant: BadgeVariant, count: Int)]
    let collaborators: [Collaborator]
    /// Credited versions grouped by era, in tracker order.
    let eras: [(eraName: String, versions: [Credited])]

    var streamable: [Credited] {
        eras.flatMap { $0.versions }.filter { $0.version.isStreamable }
    }

    /// Whether the name has a page for this role. A feature page never opens for the sheet's own artist.
    /// See DECISIONS.md::CreditPageView.swift::self-artist.
    static func hasPage(key: String, role: ArtistViewModel.CreditRole, artist: Artist, index: Index) -> Bool {
        guard index[role]?[key]?.isEmpty == false else { return false }
        return role == .producer || !selfKeys(artist).contains(key)
    }

    static func compute(
        key: String, role: ArtistViewModel.CreditRole, artist: Artist,
        index: Index, displayNames: [String: String]
    ) -> CreditProfile? {
        guard hasPage(key: key, role: role, artist: artist, index: index) else { return nil }
        let hits = (index[role]?[key] ?? []).sorted {
            ($0.era, $0.section, $0.song, $0.version) < ($1.era, $1.section, $1.song, $1.version)
        }
        let credited = hits.compactMap { credited(at: $0, in: artist) }
        guard !credited.isEmpty else { return nil }

        let other: ArtistViewModel.CreditRole = role == .producer ? .feature : .producer
        let otherRoleCount = hasPage(key: key, role: other, artist: artist, index: index)
            ? (index[other]?[key]?.count ?? 0) : 0

        let eras = groupedByEra(credited)
        let collaborators = topCollaborators(
            credited, excluding: selfKeys(artist).union([key]), displayNames: displayNames, index: index
        )

        return CreditProfile(
            name: displayNames[key] ?? key,
            role: role,
            otherRoleCount: otherRoleCount,
            songCount: Set(credited.map { [$0.hit.era, $0.hit.section, $0.hit.song] }).count,
            versionCount: credited.count,
            playableCount: credited.filter { $0.version.isStreamable }.count,
            firstEra: eras.first?.eraName ?? "",
            lastEra: eras.last?.eraName ?? "",
            bestOf: bestOf(credited),
            topEras: topEras(eras),
            quality: qualityTiers(credited),
            collaborators: collaborators,
            eras: eras
        )
    }

    // MARK: - Helpers

    private static func groupedByEra(_ credited: [Credited]) -> [(eraName: String, versions: [Credited])] {
        var eras: [(eraName: String, versions: [Credited])] = []
        for c in credited {
            if eras.last?.eraName == c.eraName {
                eras[eras.count - 1].versions.append(c)
            } else {
                eras.append((eraName: c.eraName, versions: [c]))
            }
        }
        return eras
    }

    private static func topEras(_ eras: [(eraName: String, versions: [Credited])]) -> [EraInsights.Count] {
        eras.enumerated()
            .sorted { ($0.element.versions.count, -$0.offset) > ($1.element.versions.count, -$1.offset) }
            .prefix(5)
            .map { EraInsights.Count(label: $0.element.eraName, value: $0.element.versions.count) }
    }

    private static func qualityTiers(_ credited: [Credited]) -> [(variant: BadgeVariant, count: Int)] {
        var tiers: [BadgeVariant: Int] = [:]
        for c in credited { tiers[qualityVariant(c.version.quality), default: 0] += 1 }
        return EraInsights.qualityOrder.compactMap { v in tiers[v].map { (variant: v, count: $0) } }
    }

    /// Grail first, then best, then special; ties keep tracker order.
    private static func bestOf(_ credited: [Credited]) -> [Credited] {
        let rank: [Badge] = [.grail, .best, .special]
        return credited.enumerated()
            .compactMap { item -> (rank: Int, position: Int, credited: Credited)? in
                guard let badge = item.element.version.badge.flatMap(Badge.init(rawValue:)),
                      let r = rank.firstIndex(of: badge) else { return nil }
                return (rank: r, position: item.offset, credited: item.element)
            }
            .sorted { ($0.rank, $0.position) < ($1.rank, $1.position) }
            .map { $0.credited }
    }

    private static func topCollaborators(
        _ credited: [Credited], excluding excluded: Set<String>, displayNames: [String: String], index: Index
    ) -> [Collaborator] {
        var shared: [String: (name: String, count: Int)] = [:]
        for c in credited {
            var seen = Set<String>()
            for (k, raw) in creditNames(on: c.version) where !excluded.contains(k) && seen.insert(k).inserted {
                shared[k, default: (displayNames[k] ?? raw, 0)].count += 1
            }
        }
        let collaborators = shared.map { entry in
            Collaborator(
                name: entry.value.name,
                ref: CreditRef(key: entry.key, role: collaboratorRole(entry.key, index)),
                sharedVersions: entry.value.count
            )
        }
        return Array(collaborators.sorted {
            $0.sharedVersions != $1.sharedVersions ? $0.sharedVersions > $1.sharedVersions : $0.name < $1.name
        }.prefix(8))
    }

    /// Keys of the tracker's own artist, who cannot feature on their own sheet.
    private static func selfKeys(_ artist: Artist) -> Set<String> {
        Set(EraInsights.selfNames(artist).map(CreditNames.key))
    }

    /// The role a collaborator's page opens in: the one they are credited in more often.
    private static func collaboratorRole(_ key: String, _ index: Index) -> ArtistViewModel.CreditRole {
        (index[.producer]?[key]?.count ?? 0) >= (index[.feature]?[key]?.count ?? 0) ? .producer : .feature
    }

    private static func creditNames(on version: SongVersion) -> [(key: String, name: String)] {
        [version.producers, version.featuring, version.creditedArtists, version.collaboration]
            .flatMap { CreditNames.split($0) }
            .map { (key: CreditNames.key($0), name: $0) }
    }

    private static func credited(at hit: ArtistViewModel.CreditHit, in artist: Artist) -> Credited? {
        guard artist.eras.indices.contains(hit.era) else { return nil }
        let era = artist.eras[hit.era]
        guard let sections = era.sections, sections.indices.contains(hit.section),
              sections[hit.section].songs.indices.contains(hit.song) else { return nil }
        let song = sections[hit.section].songs[hit.song]
        guard song.versions.indices.contains(hit.version) else { return nil }
        return Credited(
            eraName: era.name, eraArt: era.artUrl, song: song,
            version: song.versions[hit.version], hit: hit
        )
    }
}
