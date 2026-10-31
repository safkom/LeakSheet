import Foundation
import Testing

@testable import LeakSheet

@MainActor
struct CreditProfileTests {
    private func version(_ name: String, badge: String? = nil, producers: String? = nil,
                         featuring: String? = nil, quality: String? = nil, link: String? = nil) -> [String: Any] {
        var v: [String: Any] = ["name": name]
        if let badge { v["badge"] = badge }
        if let producers { v["producers"] = producers }
        if let featuring { v["featuring"] = featuring }
        if let quality { v["quality"] = quality }
        if let link { v["links"] = [link] }
        return v
    }

    /// Synthetic tracker: "Test Artist" features on four versions, so the sheet's own
    /// artist is recognised; "Maker" produces across two eras.
    private func artist() throws -> Artist {
        let json: [String: Any] = [
            "name": "Test Artist", "slug": "test-artist",
            "eras": [
                ["name": "First", "sections": [["name": "Main", "songs": [
                    ["base_name": "Song One", "versions": [
                        version("Song One [V1]", badge: "grail", producers: "Maker, Other", featuring: "Guest",
                                quality: "Lossless", link: "https://pillows.su/f/a1"),
                        version("Song One [V2]", badge: "best", producers: "maker", quality: "CD Quality"),
                    ]],
                    ["base_name": "Song Two", "versions": [
                        version("Song Two", producers: "Maker & Third", featuring: "Test Artist",
                                quality: "High Quality", link: "https://pillows.su/f/b2"),
                    ]],
                    ["base_name": "Song Three", "versions": [
                        version(
                            "Song Three",
                            producers: "Other",
                            featuring: "Test Artist, Guest",
                            quality: "Recording"
                        ),
                    ]],
                ]]]],
                ["name": "Second", "sections": [["name": "Main", "songs": [
                    ["base_name": "Song Four", "versions": [
                        version("Song Four", badge: "special", producers: "Other", featuring: "Test Artist, Third",
                                quality: "Low Quality"),
                    ]],
                    ["base_name": "Song Five", "versions": [
                        version("Song Five", badge: "best", producers: "Other", featuring: "Test Artist"),
                    ]],
                ]]]],
            ],
        ]
        return try JSONDecoder().decode(Artist.self, from: JSONSerialization.data(withJSONObject: json))
    }

    private func profile(_ key: String, _ role: ArtistViewModel.CreditRole, _ a: Artist) -> CreditProfile? {
        let pre = ArtistViewModel.Precomputed(artist: a)
        return CreditProfile.compute(key: key, role: role, artist: a, index: pre.creditIndex,
                                     displayNames: pre.creditDisplayNames)
    }

    @Test func `counts, active span and quality tiers`() throws {
        let a = try artist()
        let maker = try #require(profile("maker", .producer, a))
        #expect(maker.name == "Maker")
        #expect(maker.songCount == 2)
        #expect(maker.versionCount == 3)
        #expect(maker.playableCount == 2)
        #expect(maker.firstEra == "First")
        #expect(maker.lastEra == "First")
        #expect(maker.quality.map(\.variant) == [.lossless, .cd, .hq])
        #expect(maker.quality.map(\.count) == [1, 1, 1])
    }

    @Test func `a name credited in both roles reports the other role`() throws {
        let a = try artist()
        let third = try #require(profile("third", .producer, a))
        #expect(third.otherRoleCount == 1)
        #expect(try #require(profile("third", .feature, a)).otherRoleCount == 1)
        #expect(try #require(profile("maker", .producer, a)).otherRoleCount == 0)
    }

    @Test func `best of lists grail, then best, then special`() throws {
        let a = try artist()
        let other = try #require(profile("other", .producer, a))
        #expect(other.bestOf.map(\.version.name) == ["Song One [V1]", "Song Five", "Song Four"])
        let maker = try #require(profile("maker", .producer, a))
        #expect(maker.bestOf.map(\.version.name) == ["Song One [V1]", "Song One [V2]"])
    }

    @Test func `eras group in tracker order with per-era counts`() throws {
        let a = try artist()
        let other = try #require(profile("other", .producer, a))
        #expect(other.eras.map { $0.eraName } == ["First", "Second"])
        #expect(other.eras[0].versions.count == 2)
        #expect(other.topEras.map(\.label) == ["First", "Second"])
        #expect(other.topEras.map(\.value) == [2, 2])
    }

    @Test func `collaborators count shared versions and open the role they are credited in`() throws {
        let a = try artist()
        let guest = try #require(profile("guest", .feature, a))
        #expect(guest.versionCount == 2)
        let top = try #require(guest.collaborators.first)
        #expect(top.name == "Other")
        #expect(top.sharedVersions == 2)
        #expect(top.ref == CreditRef(key: "other", role: .producer))

        let maker = try #require(profile("maker", .producer, a))
        #expect(maker.collaborators.first { $0.ref.key == "other" }?.sharedVersions == 1)
        // The sheet's artist and the page's own name never appear as collaborators.
        #expect(!maker.collaborators.contains { $0.ref.key == "test artist" || $0.ref.key == "maker" })
    }

    @Test func `the sheet's own artist has no feature page`() throws {
        let a = try artist()
        #expect(profile("test artist", .feature, a) == nil)
        #expect(profile("test artist", .producer, a) == nil)
    }

    @Test func `an unknown name has no page`() throws {
        let a = try artist()
        #expect(profile("nobody", .producer, a) == nil)
        #expect(profile("nobody", .feature, a) == nil)
    }
}
