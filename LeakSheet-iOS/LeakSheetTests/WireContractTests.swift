import Foundation
import Testing

@testable import LeakSheet

/// Decodes Fixtures/contract.json, which tests/parse/test_wire_contract.py builds from the
/// API's real serializer: a field the backend renames or drops fails here and there.
struct WireContractTests {
    private final class BundleToken {}

    private func contractArtist() throws -> Artist {
        let url = try #require(Bundle(for: BundleToken.self).url(forResource: "contract", withExtension: "json"))
        return try JSONDecoder().decode(Artist.self, from: Data(contentsOf: url))
    }

    @Test func `section notes and groups decode`() throws {
        let sections = try #require(try contractArtist().eras.first?.sections)
        #expect(sections.map(\.name) == ["Early Takes", "Late Takes"])
        #expect(sections.map(\.group) == ["Deluxe Sessions", "Deluxe Sessions"])
        #expect(sections.map(\.notes) == ["(02/02/2002) (Sessions begin)", "(03/03/2003) (Sessions end)"])
    }

    @Test func `version credits, rating, sources and links decode`() throws {
        let era = try #require(try contractArtist().eras.first)
        let version = try #require(era.sections?.first?.songs.first?.versions.first)
        #expect(version.rating == 4)
        #expect(version.producers == "Maker")
        #expect(version.creditedArtists == "Guest Performer")
        #expect(version.sources == [SourceRef(label: "Proof", url: "https://example.org/proof")])
        #expect(version.links == ["https://pillows.su/f/aaa"])
    }

    @Test func `content tabs decode with their sections`() throws {
        let tab = try #require(try contractArtist().tabs?.first)
        #expect(tab.kind == "stems")
        #expect(tab.entries.map(\.section) == ["Instrumentals"])
        #expect(tab.entries.first?.links == ["https://pillows.su/f/ccc"])
    }
}
