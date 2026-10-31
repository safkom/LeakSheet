import Foundation
import Testing

@testable import LeakSheet

struct SafariItemTests {
    @Test(arguments: [
        "https://pillows.su/f/abc", "http://example.test/x", "HTTPS://Example.test/x"
    ])
    func `http and https links open`(url: String) throws {
        #expect(SafariItem.isWebURL(try #require(URL(string: url))))
    }

    @Test(arguments: [
        "javascript:alert(1)", "file:///etc/passwd", "smb://host/share", "data:text/html,x",
        "x-apple.systempreferences:com.apple.preference.security", "mailto:a@b.test",
        "ftp://host/file", "/relative/path", "https://", "tel:123"
    ])
    func `other links are ignored`(url: String) throws {
        let parsed = try #require(URL(string: url))
        #expect(!SafariItem.isWebURL(parsed))
    }
}

struct NoticeWebURLTests {
    @Test(arguments: ["N/A", "discord", "mailto:mods@x.test", "javascript:alert(1)", ""])
    func `a notice whose link is not a web URL has none`(link: String) {
        #expect(Notice(text: "t", link: link, kind: nil).webURL == nil)
    }

    @Test func `a web link is kept`() {
        #expect(Notice(text: "t", link: "https://discord.gg/x", kind: nil).webURL?.host() == "discord.gg")
    }
}
