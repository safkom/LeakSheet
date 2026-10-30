import Foundation
import Testing

@testable import LeakSheet

struct AppleMusicMatchTests {
    @Test func searchTitleDropsTags() {
        #expect(LibraryMatcher.searchTitle("Song Name [V2] (OG)") == "Song Name")
        #expect(LibraryMatcher.searchTitle("[Untitled]") == "[Untitled]")
    }

    @Test func exactTitleAndArtistOnly() {
        #expect(AppleMusicMatch.isMatch(
            artist: "Kanye West",
            title: "Runaway [V2]",
            songArtist: "Kanye West",
            songTitle: "Runaway (feat. Pusha T)"
        ))
        #expect(AppleMusicMatch.isMatch(
            artist: "Pusha T",
            title: "Runaway",
            songArtist: "Kanye West & Pusha T",
            songTitle: "Runaway"
        ))
        #expect(!AppleMusicMatch.isMatch(
            artist: "Kanye West",
            title: "Runaway",
            songArtist: "Kanye West",
            songTitle: "Runaway Love"
        ))
        #expect(!AppleMusicMatch.isMatch(
            artist: "Kanye West",
            title: "Runaway",
            songArtist: "Someone Else",
            songTitle: "Runaway"
        ))
    }
}
