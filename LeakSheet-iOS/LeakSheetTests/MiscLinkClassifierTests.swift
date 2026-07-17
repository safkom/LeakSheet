import Foundation
import Testing

@testable import LeakSheet

struct MiscLinkClassifierTests {
    // 2026-07-17: pixeldrain single files and Google Drive single-file links
    // now stream through the backend proxy.
    @Test(arguments: [
        "https://pillows.su/f/abc123",
        "https://imgur.gg/f/abc123",
        "https://music.froste.lol/song/0a1b2c3d",
        "https://krakenfiles.com/view/abc123/file.html",
        "https://pixeldrain.com/u/aBc123",
        "https://drive.google.com/file/d/1AbC-x_9/view?usp=sharing",
    ])
    func `known streamable hosts classify as stream`(url: String) {
        #expect(MiscLinkClassifier.classify(url) == .stream)
    }

    @Test(arguments: [
        "https://i.imgur.com/abc123.jpg",
        "https://example.com/cover.png",
        "https://i.ibb.co/xyz/photo.jpeg",
        "https://postimg.cc/image.webp",
    ])
    func `image hosts and extensions classify as image`(url: String) {
        #expect(MiscLinkClassifier.classify(url) == .image)
    }

    // 2026-07-17: YouTube/Vimeo moved from .video to .embed (official
    // in-app embed players); .video now means a direct video file.
    @Test(arguments: [
        "https://example.com/clip.mp4",
        "https://example.com/clip.mov",
    ])
    func `video file extensions classify as video`(url: String) {
        #expect(MiscLinkClassifier.classify(url) == .video)
    }

    @Test(arguments: [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://vimeo.com/123456789",
        "https://soundcloud.com/artist/track",
        "https://on.soundcloud.com/abc123",
        "https://m.soundcloud.com/artist/track",
    ])
    func `embeddable hosts classify as embed`(url: String) {
        #expect(MiscLinkClassifier.classify(url) == .embed)
    }

    // 2026-07-17: gdrive single-file links became .stream; folders and
    // uc?id= forms stay archive so unknown payloads open in Safari.
    @Test(arguments: [
        "https://example.com/archive.zip",
        "https://mega.nz/file/abc123",
        "https://www.mediafire.com/file/abc123",
        "https://drive.google.com/drive/folders/1AbCdEf",
    ])
    func `archive hosts and extensions classify as archive`(url: String) {
        #expect(MiscLinkClassifier.classify(url) == .archive)
    }

    @Test(arguments: [
        "https://www.instagram.com/p/abc123",
        "https://twitter.com/user/status/123",
        "https://web.archive.org/web/2020/https://example.com",
        "not a url at all",
    ])
    func `anything unrecognized falls back to a generic link`(url: String) {
        #expect(MiscLinkClassifier.classify(url) == .link)
    }

    @Test(arguments: [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "YouTube"),
        ("https://youtu.be/dQw4w9WgXcQ", "YouTube"),
        ("https://vimeo.com/123456789", "Vimeo"),
        ("https://soundcloud.com/artist/track", "SoundCloud"),
        ("https://drive.google.com/file/d/abc/view", "Google Drive"),
        ("https://mega.nz/file/abc", "Mega"),
        ("https://www.mediafire.com/file/abc", "MediaFire"),
        ("https://web.archive.org/web/2020/x", "Archive"),
        ("https://www.instagram.com/p/abc", "Instagram"),
        ("https://twitter.com/user/status/1", "Twitter/X"),
        ("https://x.com/user/status/1", "Twitter/X"),
        ("https://example.com/page", "example.com"),
    ])
    func `label derives a short host name`(url: String, expected: String) {
        let kind = MiscLinkClassifier.classify(url)
        #expect(MiscLinkClassifier.label(for: url, kind: kind) == expected)
    }

    @Test func `image links use themselves as the thumbnail`() {
        let url = "https://i.imgur.com/abc123.jpg"
        #expect(MiscLinkClassifier.thumbnailURL(for: url, kind: .image) == url)
    }

    // 2026-07-17: YouTube links are .embed now — thumbnail derivation
    // follows the kind.
    @Test(arguments: [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ])
    func `YouTube thumbnail is derived from the video id in any URL form`(url: String, id: String) {
        #expect(MiscLinkClassifier.thumbnailURL(for: url, kind: .embed) == "https://img.youtube.com/vi/\(id)/hqdefault.jpg")
    }

    @Test func `embed links with no derivable id have no thumbnail`() {
        // Vimeo has no predictable thumbnail path without an API call.
        #expect(MiscLinkClassifier.thumbnailURL(for: "https://vimeo.com/123456789", kind: .embed) == nil)
    }

    @Test(arguments: [MiscLinkKind.stream, .archive, .link, .video])
    func `stream, archive, video-file, and generic links have no thumbnail`(kind: MiscLinkKind) {
        #expect(MiscLinkClassifier.thumbnailURL(for: "https://example.com/x", kind: kind) == nil)
    }

    // MARK: - Embed URL builders

    @Test func `youtube embed url`() {
        #expect(
            MiscLinkClassifier.embedURL(for: "https://www.youtube.com/watch?v=dQw4w9WgXcQ")?.absoluteString
                == "https://www.youtube.com/embed/dQw4w9WgXcQ?playsinline=1"
        )
    }

    @Test func `vimeo embed url`() {
        #expect(
            MiscLinkClassifier.embedURL(for: "https://vimeo.com/123456789")?.absoluteString
                == "https://player.vimeo.com/video/123456789"
        )
    }

    @Test func `soundcloud embed url wraps the original`() {
        let embed = MiscLinkClassifier.embedURL(for: "https://soundcloud.com/artist/track")
        let s = embed?.absoluteString ?? ""
        #expect(s.hasPrefix("https://w.soundcloud.com/player/?url="))
        // .alphanumerics escaping percent-encodes every non-alphanumeric,
        // including dots — decode to verify the wrapped original.
        let query = s.replacingOccurrences(of: "https://w.soundcloud.com/player/?url=", with: "")
            .replacingOccurrences(of: "&auto_play=false", with: "")
        #expect(query.removingPercentEncoding == "https://soundcloud.com/artist/track")
    }

    @Test func `non-embeddable links have no embed url`() {
        #expect(MiscLinkClassifier.embedURL(for: "https://example.com/page") == nil)
    }
}
