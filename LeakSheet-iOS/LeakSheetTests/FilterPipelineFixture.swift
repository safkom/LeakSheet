import Foundation
import SwiftUI
import Testing

@testable import LeakSheet

/// The small two-era tracker the filter-pipeline tests run against.
protocol FilterPipelineFixture {}

extension FilterPipelineFixture {

    func version(
        _ name: String, tag: String? = nil, badge: String? = nil,
        available: String? = "Full", quality: String? = "High Quality",
        leakDate: String? = nil, previewDate: String? = nil,
        link: String? = "https://pillows.su/f/abc123",
        altTitles: [String]? = nil
    ) -> SongVersion {
        SongVersion(
            name: name, versionTag: tag, badge: badge, featuring: nil,
            producers: nil, collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: altTitles,
            notes: nil, ogFilename: nil, ogFilenames: nil, samples: nil,
            trackLength: nil, fileDate: nil, leakDate: leakDate, previewDate: previewDate,
            availableLength: available, quality: quality, streaming: nil,
            links: link.map { [$0] }, dateOfRecording: nil, type: nil,
            sources: nil, rating: nil
        )
    }

    func song(_ baseName: String, versions: [SongVersion]) -> Song {
        Song(baseName: baseName, songKey: nil, versions: versions, badge: nil)
    }

    func era(_ name: String, songs: [Song]) -> Era {
        Era(
            name: name, altNames: nil, description: nil, timeline: nil,
            artUrl: nil,
            sections: [Section(name: "", group: nil, songs: songs)],
            songCount: nil, versionCount: nil
        )
    }

    var artist: Artist {
        let eraA = era("Era A", songs: [
            song("Starred Song", versions: [
                version("Starred Song", tag: "V1", badge: "best", leakDate: "01/15/2024"),
                version("Starred Song", tag: "V2", available: "Snippet", leakDate: "03/20/2024")
            ]),
            song("Plain Song", versions: [
                version("Plain Song", leakDate: "02/10/2024", altTitles: ["Alias One"])
            ])
        ])
        let eraB = era("Era B", songs: [
            song("Snippet Only", versions: [
                version("Snippet Only", available: "Snippet", leakDate: "04/01/2024")
            ])
        ])
        return Artist(
            name: "Test Artist", slug: "test-artist", sourceUrl: nil,
            eras: [eraA, eraB], trackerStats: nil,
            notices: nil, totalSongs: nil, totalVersions: nil,
            tabs: nil
        )
    }

    func compute(_ state: FilterState) -> FilteredContent {
        var stats: [String: ArtistViewModel.Stats] = [:]
        for era in artist.eras {
            stats[era.name] = ArtistViewModel.computeEraStats(era)
        }
        return ArtistViewModel.computeContent(artist: artist, state: state, eraStats: stats)
    }
}
