import Foundation
import Testing

@testable import LeakSheet

struct CreditNamesTests {
    @Test func `credit split breaks on each separator`() {
        #expect(CreditNames.split("A, B") == ["A", "B"])
        #expect(CreditNames.split("A & B") == ["A", "B"])
        #expect(CreditNames.split("A + B") == ["A", "B"])
        #expect(CreditNames.split("A / B") == ["A", "B"])
        #expect(CreditNames.split("A; B") == ["A", "B"])
    }

    @Test func `credit split breaks on whole-word x and and`() {
        #expect(CreditNames.split("A x B") == ["A", "B"])
        #expect(CreditNames.split("A X B") == ["A", "B"])
        #expect(CreditNames.split("A and B") == ["A", "B"])
        #expect(CreditNames.split("A AND B") == ["A", "B"])
    }

    @Test func `credit split leaves names containing x and or ft unbroken`() {
        #expect(CreditNames.split("Maxwell") == ["Maxwell"])
        #expect(CreditNames.split("Alexander") == ["Alexander"])
        #expect(CreditNames.split("Brandon") == ["Brandon"])
    }

    @Test func `credit split strips feat, ft and prod prefixes`() {
        #expect(CreditNames.split("feat. A") == ["A"])
        #expect(CreditNames.split("ft. A") == ["A"])
        #expect(CreditNames.split("Prod. A") == ["A"])
        #expect(CreditNames.split("PROD. BY A & feat. B") == ["A", "B"])
    }

    @Test func `credit split drops placeholders, blanks and empty input`() {
        #expect(CreditNames.split("A, ???") == ["A"])
        #expect(CreditNames.split("???") == [])
        #expect(CreditNames.split(nil) == [])
        #expect(CreditNames.split("") == [])
        #expect(CreditNames.split("  ") == [])
    }

    @Test func `credit key folds case`() {
        #expect(CreditNames.key("Maker") == CreditNames.key("maker"))
        #expect(CreditNames.key("Maker") == "maker")
    }

    private func decodeArtist(_ json: String) throws -> Artist {
        try JSONDecoder().decode(Artist.self, from: Data(json.utf8))
    }

    @Test func `credit index maps producers and features to version positions`() throws {
        let artist = try decodeArtist("""
        {"name": "Test", "slug": "test", "eras": [{"name": "Era One", "sections": [{"name": "Main", "songs": [
          {"base_name": "Song A", "versions": [
            {"name": "v1", "producers": "Maker", "featuring": "feat. Guest"},
            {"name": "v2", "producers": "maker & Other"}]},
          {"base_name": "Song B", "versions": [
            {"name": "v1", "producers": "Maker", "collaboration": "Guest"}]}
        ]}]}]}
        """)
        let index = ArtistViewModel.Precomputed(artist: artist)

        #expect(index.creditIndex[.producer]?["maker"] == [
            .init(era: 0, section: 0, song: 0, version: 0),
            .init(era: 0, section: 0, song: 0, version: 1),
            .init(era: 0, section: 0, song: 1, version: 0)
        ])
        #expect(index.creditIndex[.producer]?["other"] == [.init(era: 0, section: 0, song: 0, version: 1)])
        #expect(index.creditIndex[.feature]?["guest"] == [
            .init(era: 0, section: 0, song: 0, version: 0),
            .init(era: 0, section: 0, song: 1, version: 0)
        ])
        #expect(index.creditIndex[.feature]?["maker"] == nil)
        #expect(index.creditDisplayNames["maker"] == "Maker")
        #expect(index.creditDisplayNames["other"] == "Other")
    }

    @Test func `credit display name picks the most common spelling`() throws {
        let artist = try decodeArtist("""
        {"name": "Test", "slug": "test", "eras": [{"name": "Era One", "sections": [{"name": "Main", "songs": [
          {"base_name": "Song A", "versions": [
            {"name": "v1", "producers": "maker"},
            {"name": "v2", "producers": "maker"},
            {"name": "v3", "producers": "Maker"}]}
        ]}]}]}
        """)
        let index = ArtistViewModel.Precomputed(artist: artist)
        #expect(index.creditDisplayNames["maker"] == "maker")
    }

    /// Timing is logged for a human to read; there is no threshold, so it cannot flake.
    @Test func `credit index timing over ten thousand versions`() throws {
        let songs: [[String: Any]] = (0..<1000).map { i in
            [
                "base_name": "Song \(i)",
                "versions": (0..<10).map { j in
                    [
                        "name": "v\(j)",
                        "producers": "Producer \(i % 50)",
                        "featuring": "Guest \(j % 7) & Feat \(i % 13)"
                    ] as [String: Any]
                }
            ]
        }
        let root: [String: Any] = [
            "name": "Synthetic", "slug": "synthetic",
            "eras": [["name": "Era", "sections": [["name": "Main", "songs": songs]]]]
        ]
        let artist = try JSONDecoder().decode(Artist.self, from: JSONSerialization.data(withJSONObject: root))

        let start = ContinuousClock.now
        let index = ArtistViewModel.Precomputed(artist: artist)
        let elapsed = start.duration(to: .now)
        print("credit index: 10000 versions built in \(elapsed)")

        #expect(index.creditIndex[.producer]?["producer 0"]?.count == 200)
    }
}
