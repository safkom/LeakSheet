import Foundation
import Testing

@testable import LeakSheet

struct MiscLinkClassifierTests {
    @Test(arguments: [
        "https://pillows.su/f/abc123",
        "https://imgur.gg/f/abc123",
        "https://music.froste.lol/song/0a1b2c3d",
        "https://krakenfiles.com/view/abc123/file.html",
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

    @Test(arguments: [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://vimeo.com/123456789",
        "https://example.com/clip.mp4",
    ])
    func `video hosts and extensions classify as video`(url: String) {
        #expect(MiscLinkClassifier.classify(url) == .video)
    }

    @Test(arguments: [
        "https://example.com/archive.zip",
        "https://mega.nz/file/abc123",
        "https://www.mediafire.com/file/abc123",
        "https://drive.google.com/file/d/abc123/view",
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

    @Test(arguments: [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ])
    func `YouTube thumbnail is derived from the video id in any URL form`(url: String, id: String) {
        #expect(MiscLinkClassifier.thumbnailURL(for: url, kind: .video) == "https://img.youtube.com/vi/\(id)/hqdefault.jpg")
    }

    @Test func `video links with no derivable id have no thumbnail`() {
        // Vimeo has no predictable thumbnail path without an API call.
        #expect(MiscLinkClassifier.thumbnailURL(for: "https://vimeo.com/123456789", kind: .video) == nil)
    }

    @Test(arguments: [MiscLinkKind.stream, .archive, .link])
    func `stream, archive, and generic links have no thumbnail`(kind: MiscLinkKind) {
        #expect(MiscLinkClassifier.thumbnailURL(for: "https://example.com/x", kind: kind) == nil)
    }
}

struct MiscEntryMediaLinksTests {
    private func entry(links: [String]) -> MiscEntry {
        MiscEntry(
            eraName: "Test Era", name: "Test Entry", notes: nil, entryType: nil,
            date: nil, length: nil, available: nil, quality: nil, streaming: nil,
            links: links, sourceTab: "misc"
        )
    }

    @Test func `mediaLinks classifies every link and preserves order`() {
        let e = entry(links: [
            "https://www.instagram.com/p/abc",
            "https://web.archive.org/web/2020/x",
            "https://pillows.su/f/abc123",
        ])
        let kinds = e.mediaLinks.map(\.kind)
        #expect(kinds == [.link, .link, .stream])
    }

    @Test func `previewImageURL picks the first link with a derivable thumbnail`() {
        let e = entry(links: [
            "https://web.archive.org/web/2020/x",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://i.imgur.com/abc123.jpg",
        ])
        // The YouTube link comes before the direct image link, and YouTube
        // has a derivable thumbnail, so it wins.
        #expect(e.previewImageURL == "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    }

    @Test func `previewImageURL is nil when no link has a derivable thumbnail`() {
        let e = entry(links: ["https://mega.nz/file/abc", "https://example.com/page"])
        #expect(e.previewImageURL == nil)
    }
}
