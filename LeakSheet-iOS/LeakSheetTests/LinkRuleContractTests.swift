import Foundation
import Testing

@testable import LeakSheet

/// Replays Fixtures/stream_links.json, which tests/parse/test_link_rule_contract.py builds from
/// the backend's own resolver and normalizer: a rule the two sides read differently fails here.
struct LinkRuleContractTests {
    private final class BundleToken {}

    private struct Vectors: Decodable {
        struct StreamLink: Decodable { let link: String; let provider: String? }
        struct TrackerURL: Decodable { let raw: String; let normalized: String }
        let streamLinks: [StreamLink]
        let trackerUrls: [TrackerURL]

        enum CodingKeys: String, CodingKey {
            case streamLinks = "stream_links"
            case trackerUrls = "tracker_urls"
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

    @Test func `every tracker URL normalizes the way the backend does`() throws {
        let urls = try vectors().trackerUrls
        #expect(!urls.isEmpty)
        for v in urls {
            #expect(TrackerURLNormalizer.normalize(v.raw) == v.normalized, "\(v.raw.debugDescription)")
        }
    }
}
