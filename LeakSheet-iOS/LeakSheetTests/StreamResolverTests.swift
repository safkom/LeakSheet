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

    // MARK: - Google redirect wrapper + nested-URL encoding

    /// Google Docs glues its redirect params straight onto the path on these —
    /// no `?` — so the id failed isID and 25 links in the live corpus showed no
    /// play affordance at all.
    @Test func `a pillows link with glued google tracking is still streamable`() {
        let link = "https://pillows.su/f/274b47d9d17ae027929947fc28218bde"
            + "&sa=D&source=editors&ust=1768409055962135&usg=AOvVaw0brfg"
        #expect(StreamResolver.target(for: link) == .pillows(id: "274b47d9d17ae027929947fc28218bde"))
        #expect(StreamResolver.originalQualityURL(for: link)?.absoluteString
                == "https://api.pillows.su/api/download/274b47d9d17ae027929947fc28218bde")
    }

    @Test func `the wrapper is stripped before the link is proxied`() {
        let link = "https://pillows.su/f/abc123&sa=D&source=editors&ust=1&usg=X"
        let proxied = try! #require(StreamResolver.streamURL(for: link)).absoluteString
        #expect(!proxied.contains("sa%3DD"))
        #expect(!proxied.contains("&sa="))
        #expect(proxied.contains("pillows.su%2Ff%2Fabc123"))
    }

    /// Only a tail that is ENTIRELY wrapper params may be dropped — a real
    /// parameter that happens to sit beside them must survive.
    @Test func `a genuine parameter is not mistaken for tracking`() {
        let link = "https://drive.google.com/open?id=1ABCdef&sa=D&keep=me"
        #expect(StreamResolver.canonical(link) == link)
    }

    /// The link is nested as the value of the backend's own `url=` param, so
    /// every reserved character has to be escaped or the value is truncated at
    /// the first `&` — which dropped the file id on `uc?export=download&id=…`.
    @Test func `nested url escapes the separators that would split it`() {
        let link = "https://drive.google.com/uc?export=download&id=1ABCdefGHIjkl"
        let proxied = try! #require(StreamResolver.streamURL(for: link)).absoluteString
        let value = String(proxied.split(separator: "=", maxSplits: 1).last!)
        #expect(!value.contains("&"), "an unescaped & splits the value: \(value)")
        #expect(!value.contains("?"))
        #expect(value.removingPercentEncoding == link)
    }

    @Test func `drive links keep working with their own params attached`() {
        let link = "https://drive.google.com/open?id=1M8LE0Rog4LMTykX35CbihvCRGYfBVrCV&usp=drive_copy"
        #expect(StreamResolver.target(for: link) == .gdrive)
        let proxied = try! #require(StreamResolver.streamURL(for: link)).absoluteString
        #expect(proxied.contains("usp%3Ddrive_copy"))
    }
}
