import Foundation
import Testing

@testable import LeakSheet

struct StreamResolverTests {
    @Test(arguments: [
        "https://pillows.su/f/58876d9f36b768640439466088764e87",
        "https://www.pillowcase.su/f/abc123",
        "https://pillows.su/f/abc123?x=1",
        "https://imgur.gg/f/wGLEqSB",
        "https://temp.imgur.gg/f/wGLEqSB",
        "https://music.froste.lol/song/0a1b2c3d",
        "https://krakenfiles.com/view/FJmpAhYHMp/file.html",
        "HTTPS://PILLOWS.SU/F/ABC123",  // case-insensitive
    ])
    func `known hosts are streamable`(url: String) {
        #expect(StreamResolver.isStreamableURL(url))
    }

    @Test(arguments: [
        "https://youtube.com/watch?v=abc",
        "https://mega.nz/file/abc",
        "https://pillows.su/about",              // wrong path shape
        "https://notpillows.su/f/abc123",        // wrong host
        "https://krakenfiles.com/view/X/other",  // missing file.html
        "https://music.froste.lol/song/XYZ",     // non-hex hash
        "",
    ])
    func `unknown hosts and malformed links are not streamable`(url: String) {
        #expect(!StreamResolver.isStreamableURL(url))
    }

    @Test func `original quality maps pillows to the download API`() {
        let url = StreamResolver.originalQualityURL(for: "https://pillows.su/f/abc123")
        #expect(url?.absoluteString == "https://api.pillows.su/api/download/abc123")
    }

    @Test func `original quality maps froste to the download endpoint`() {
        let url = StreamResolver.originalQualityURL(for: "https://music.froste.lol/song/0a1b2c")
        #expect(url?.absoluteString == "https://music.froste.lol/song/0a1b2c/download")
    }

    @Test func `original quality for kraken routes through the stream proxy`() {
        let url = StreamResolver.originalQualityURL(for: "https://krakenfiles.com/view/FJmpAhYHMp/file.html")
        #expect(url?.absoluteString.contains("/stream?url=") == true)
    }

    @Test func `stream URL is nil for unsupported links`() {
        #expect(StreamResolver.streamURL(for: "https://youtube.com/watch?v=1") == nil)
        #expect(StreamResolver.originalQualityURL(for: "https://mega.nz/file/x") == nil)
    }
}
