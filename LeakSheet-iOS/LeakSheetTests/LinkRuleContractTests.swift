import Foundation
import Testing

@testable import LeakSheet

private struct StreamLinkVector: Decodable { let link: String; let provider: String? }
private struct TrackerURLVector: Decodable { let raw: String; let normalized: String }
private struct KnownLinkVector: Decodable { let link: String; let python: String?; let swift: String? }
private struct KnownURLVector: Decodable { let raw: String; let python: String?; let swift: String }

/// Replays Fixtures/stream_links.json, which tests/parse/test_link_rule_contract.py builds from
/// the backend's own resolver and normalizer: a rule the two sides read differently fails here.
/// The known differences are pinned both ways, so closing one also fails until it is moved.
struct LinkRuleContractTests {
    private final class BundleToken {}

    private struct Vectors: Decodable {
        let streamLinks: [StreamLinkVector]
        let trackerUrls: [TrackerURLVector]
        let knownDifferences: [KnownLinkVector]
        let knownUrlDifferences: [KnownURLVector]

        enum CodingKeys: String, CodingKey {
            case streamLinks = "stream_links"
            case trackerUrls = "tracker_urls"
            case knownDifferences = "known_differences"
            case knownUrlDifferences = "known_url_differences"
        }
    }

    private func vectors() throws -> Vectors {
        let url = try #require(Bundle(for: BundleToken.self).url(forResource: "stream_links", withExtension: "json"))
        return try JSONDecoder().decode(Vectors.self, from: Data(contentsOf: url))
    }

    @Test func `every link resolves to the provider the backend names`() throws {
        let links = try vectors().streamLinks
        #expect(!links.isEmpty)
        for v in links {
            #expect(StreamResolver.provider(for: v.link) == v.provider, "\(v.link.debugDescription)")
        }
    }

    @Test func `known link differences are still exactly the recorded ones`() throws {
        let known = try vectors().knownDifferences
        #expect(!known.isEmpty)
        for d in known {
            let got = StreamResolver.provider(for: d.link)
            #expect(got == d.swift, "\(d.link.debugDescription): Swift answers \(got ?? "nil")")
            #expect(got != d.python, "\(d.link.debugDescription) now agrees with Python: move it to the shared vectors")
        }
    }

    @Test func `known URL differences are still exactly the recorded ones`() throws {
        let known = try vectors().knownUrlDifferences
        #expect(!known.isEmpty)
        for d in known {
            let got = TrackerURLNormalizer.normalize(d.raw)
            #expect(got == d.swift, "\(d.raw.debugDescription): Swift answers \(got)")
            #expect(got != d.python, "\(d.raw.debugDescription) now agrees with Python: move it to the shared vectors")
        }
    }

    @Test func `every tracker URL normalizes the way the backend does`() throws {
        let urls = try vectors().trackerUrls
        #expect(!urls.isEmpty)
        for v in urls {
            #expect(TrackerURLNormalizer.normalize(v.raw) == v.normalized, "\(v.raw.debugDescription)")
        }
    }
}
