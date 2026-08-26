import Foundation
import Testing

@testable import LeakSheet

/// Decoding tests for the 2026-07 API additions: `Song.song_key`,
/// `Artist.tabs`, and `FileMetadata.media_kind`. All are optional so older
/// cached payloads and older backends keep decoding.
struct ModelsDecodingTests {
    private func decodeArtist(_ json: String) throws -> Artist {
        try JSONDecoder().decode(Artist.self, from: Data(json.utf8))
    }

    private func decodeSong(_ json: String) throws -> Song {
        try JSONDecoder().decode(Song.self, from: Data(json.utf8))
    }

    @Test func `song decodes song_key`() throws {
        let song = try decodeSong(#"{"base_name": "This One Here", "versions": [], "song_key": "this one here"}"#)
        #expect(song.songKey == "this one here")
    }

    @Test func `song without song_key decodes`() throws {
        let song = try decodeSong(#"{"base_name": "Old Payload", "versions": []}"#)
        #expect(song.songKey == nil)
    }

    @Test func `song version decodes credited_artists`() throws {
        // The backend routes a dedicated Artist column into credited_artists
        // (distinct from featuring); verify the CodingKey maps end-to-end.
        let song = try decodeSong(#"""
        {"base_name": "Collab Track", "versions": [
            {"name": "Collab Track", "credited_artists": "Some Performer", "featuring": "A Guest"}
        ]}
        """#)
        #expect(song.versions.first?.creditedArtists == "Some Performer")
        #expect(song.versions.first?.featuring == "A Guest")
    }

    @Test func `song version without credited_artists decodes`() throws {
        let song = try decodeSong(#"{"base_name": "T", "versions": [{"name": "T"}]}"#)
        #expect(song.versions.first?.creditedArtists == nil)
    }

    @Test func `artist decodes tabs`() throws {
        let artist = try decodeArtist("""
        {"name": "Test", "slug": "test", "eras": [],
         "tabs": [{"kind": "released", "name": "📻 Released",
                   "entries": [{"era_name": "Donda", "name": "Hurricane",
                                "links": ["https://pillows.su/f/abc"],
                                "source_tab": "released"}]}]}
        """)
        let tabs = try #require(artist.tabs)
        #expect(tabs.count == 1)
        #expect(tabs[0].kind == "released")
        #expect(tabs[0].name == "📻 Released")
        #expect(tabs[0].entries.count == 1)
        #expect(tabs[0].entries[0].name == "Hurricane")
        #expect(tabs[0].entries[0].sourceTab == "released")
    }

    @Test func `artist without tabs decodes`() throws {
        let artist = try decodeArtist(#"{"name": "Test", "slug": "test", "eras": []}"#)
        #expect(artist.tabs == nil)
    }

    @Test func `file metadata decodes media_kind`() throws {
        let meta = try JSONDecoder().decode(
            FileMetadata.self,
            from: Data(#"{"provider": "pillows", "container": "MPEG-4", "codec": "H.264", "media_kind": "video"}"#.utf8)
        )
        #expect(meta.mediaKind == "video")
    }

    @Test func `file metadata without media_kind decodes`() throws {
        let meta = try JSONDecoder().decode(
            FileMetadata.self,
            from: Data(#"{"provider": "pillows"}"#.utf8)
        )
        #expect(meta.mediaKind == nil)
    }
    // MARK: - 2026-08: fields the API already sent but nothing decoded

    @Test func `song version decodes preview_date`() throws {
        let song = try decodeSong(#"{"base_name": "Snippet Only", "versions": [{"name": "Snippet Only", "preview_date": "Mar 20, 2023"}]}"#)
        #expect(song.versions.first?.previewDate == "Mar 20, 2023")
    }

    @Test func `tracker stats decode the link totals`() throws {
        let artist = try decodeArtist(#"{"name": "A", "slug": "a", "eras": [], "tracker_stats": {"total_links": 1203, "missing_links": 42, "not_available_links": 7}}"#)
        #expect(artist.trackerStats?.totalLinks == 1203)
        #expect(artist.trackerStats?.notAvailableLinks == 7)
    }

    /// ArtistGrid encodes "partially working" as neither true nor false, so
    /// only a definite false may warn in Explore.
    @Test func `discovery artist decodes working_links as a tri-state`() throws {
        func decode(_ json: String) throws -> DiscoveryArtist {
            try JSONDecoder().decode(DiscoveryArtist.self, from: Data(json.utf8))
        }
        #expect(try decode(#"{"name": "A", "url": "u", "working_links": false}"#).workingLinks == false)
        #expect(try decode(#"{"name": "A", "url": "u", "working_links": true}"#).workingLinks == true)
        #expect(try decode(#"{"name": "A", "url": "u"}"#).workingLinks == nil)
    }
}
