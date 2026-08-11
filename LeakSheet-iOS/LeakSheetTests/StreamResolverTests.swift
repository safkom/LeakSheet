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
        // 2026-07-17: pixeldrain files + Google Drive single files stream
        // through the backend proxy.
        "https://pixeldrain.com/u/aBc123",
        "https://www.pixeldrain.com/u/xY9z",
        "https://drive.google.com/file/d/1AbC-x_9/view?usp=sharing",
        "https://drive.google.com/file/d/1AbC-x_9",
        // 2026-07-21: open?id= / uc?id= now stream too (backend parity —
        // streaming._extract_gdrive_id resolves all three forms).
        "https://drive.google.com/open?id=1AbC-x_9",
        "https://drive.google.com/uc?id=1AbC-x_9&export=download",
        "https://drive.google.com/uc?export=download&id=1AbC-x_9",
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
        "https://pixeldrain.com/l/abc123",       // pixeldrain LIST, not a file
        "https://drive.google.com/drive/folders/1AbCdEf",  // gdrive folder (no file id)
        "",
    ])
    func `unknown hosts and malformed links are not streamable`(url: String) {
        #expect(!StreamResolver.isStreamableURL(url))
    }

    @Test func `pixeldrain original quality is the direct file API`() {
        let url = StreamResolver.originalQualityURL(for: "https://pixeldrain.com/u/aBc123")
        #expect(url?.absoluteString == "https://pixeldrain.com/api/file/aBc123?download")
    }

    @Test func `gdrive original quality routes through the stream proxy`() {
        let url = StreamResolver.originalQualityURL(for: "https://drive.google.com/file/d/1AbC/view")
        #expect(url?.absoluteString.contains("/stream?url=") == true)
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

    @Test func `original quality for imgur routes through the stream proxy`() {
        // The /f/{id} link serves text/html, and the CDN URL is only
        // discoverable via imgur's API — which only the backend calls. Handing
        // AVPlayer the page URL failed with "Operation Stopped".
        for link in ["https://imgur.gg/f/002XdG5", "https://temp.imgur.gg/f/002XdG5"] {
            let url = StreamResolver.originalQualityURL(for: link)
            #expect(url?.absoluteString.contains("/stream?url=") == true, "\(link)")
        }
    }

    @Test func `no original quality URL points at a viewer page`() {
        // Blanket guard: every supported host's "original" must be a file
        // endpoint or the proxy, never a human-facing page.
        let links = [
            "https://pillows.su/f/abc123",
            "https://music.froste.lol/song/0a1b2c",
            "https://imgur.gg/f/002XdG5",
            "https://krakenfiles.com/view/FJmpAhYHMp/file.html",
            "https://pixeldrain.com/u/aBc123",
            "https://drive.google.com/file/d/1AbC/view",
        ]
        for link in links {
            guard let url = StreamResolver.originalQualityURL(for: link)?.absoluteString else {
                Issue.record("no original-quality URL for \(link)")
                continue
            }
            let isPage = url.contains("/f/") || url.contains("/u/") || url.contains("/view")
            #expect(!isPage || url.contains("/stream?url="), "\(link) → \(url)")
        }
    }

    @Test func `stream URL is nil for unsupported links`() {
        #expect(StreamResolver.streamURL(for: "https://youtube.com/watch?v=1") == nil)
        #expect(StreamResolver.originalQualityURL(for: "https://mega.nz/file/x") == nil)
    }
}
