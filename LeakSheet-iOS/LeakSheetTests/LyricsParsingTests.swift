import Foundation
import Testing

@testable import LeakSheet

struct LyricsParsingTests {
    @Test func searchTitleDropsTags() {
        #expect(LyricsParsing.searchTitle("Song Name [V2] (OG)") == "Song Name")
        #expect(LyricsParsing.searchTitle("[Untitled]") == "[Untitled]")
    }

    @Test func parseLRCHandlesMultiStampsAndMetadata() {
        let lines = LyricsParsing.parseLRC("[ar:Someone]\n[00:12.50]first\n[00:05.00][00:30.00]chorus\n[00:40.00]")
        #expect(lines.map(\.text) == ["chorus", "first", "chorus", ""])
        #expect(lines.map(\.time) == [5, 12.5, 30, 40])
    }

    @Test func currentIndexIsLastStartedLine() {
        let lyrics = Lyrics(plain: nil, synced: LyricsParsing.parseLRC("[00:05.00]a\n[00:10.00]b"))
        #expect(lyrics.currentIndex(at: 2) == nil)
        #expect(lyrics.currentIndex(at: 10) == 1)
    }

    private func hit(_ name: String, _ duration: Double, synced: String? = nil, plain: String? = nil) -> LyricsParsing.Hit {
        LyricsParsing.Hit(trackName: name, duration: duration, plainLyrics: plain, syncedLyrics: synced)
    }

    @Test func pickRequiresTitleMatch() {
        let lyrics = LyricsParsing.pick([hit("Other", 200, plain: "x")], title: "Song", duration: 200)
        #expect(lyrics.isEmpty)
    }

    @Test func pickDropsSyncedWhenCutDiffers() {
        let hits = [hit("Song", 300, synced: "[00:01.00]a", plain: "a")]
        let far = LyricsParsing.pick(hits, title: "Song", duration: 200)
        #expect(far.synced.isEmpty && far.plain == "a")
        let near = LyricsParsing.pick(hits, title: "Song", duration: 295)
        #expect(near.synced.count == 1)
    }
}

struct AppleMusicMatchTests {
    @Test func exactTitleAndArtistOnly() {
        #expect(AppleMusicMatch.isMatch(artist: "Kanye West", title: "Runaway [V2]", songArtist: "Kanye West", songTitle: "Runaway (feat. Pusha T)"))
        #expect(AppleMusicMatch.isMatch(artist: "Pusha T", title: "Runaway", songArtist: "Kanye West & Pusha T", songTitle: "Runaway"))
        #expect(!AppleMusicMatch.isMatch(artist: "Kanye West", title: "Runaway", songArtist: "Kanye West", songTitle: "Runaway Love"))
        #expect(!AppleMusicMatch.isMatch(artist: "Kanye West", title: "Runaway", songArtist: "Someone Else", songTitle: "Runaway"))
    }
}
