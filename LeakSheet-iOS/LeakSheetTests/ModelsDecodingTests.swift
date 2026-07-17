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
}
