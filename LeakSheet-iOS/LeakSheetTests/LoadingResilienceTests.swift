import Foundation
import Testing

@testable import LeakSheet

/// Pins the two decisions behind "era covers render blank" and
/// "Contacting server… covers the whole load".
@Suite("Loading resilience")
struct LoadingResilienceTests {
    // MARK: - Image retry classification
    //
    // loadImage ignored the HTTP status entirely: a 429 body ("Too Many
    // Requests") went into ImageIO, failed to decode, and came back nil —
    // indistinguishable from a genuinely missing image. Callers then render a
    // placeholder and never ask again. With /image-proxy sharing the /sheet
    // rate-limit bucket, a quarter of all cover requests took that path.

    @Test(arguments: [429, 500, 502, 503, 504, 599])
    func `throttles and server errors are worth retrying`(status: Int) {
        #expect(ImageCache.isTransient(status))
    }

    @Test(arguments: [200, 204, 301, 304, 400, 403, 404, 410, 418])
    func `everything else is final`(status: Int) {
        #expect(!ImageCache.isTransient(status))
    }

    private func response(retryAfter: String?) -> HTTPURLResponse {
        HTTPURLResponse(
            url: URL(string: "https://example.com/image-proxy")!,
            statusCode: 429,
            httpVersion: "HTTP/1.1",
            headerFields: retryAfter.map { ["Retry-After": $0] }
        )!
    }

    @Test func `retry delay defaults to a second when the server is silent`() {
        #expect(ImageCache.retryDelay(after: response(retryAfter: nil)) == 1)
    }

    @Test func `retry delay honours Retry-After`() {
        #expect(ImageCache.retryDelay(after: response(retryAfter: "2")) == 2)
    }

    /// The backend sends Retry-After: 60 (the rate-limit window). Obeying it
    /// literally would park an era card for a minute; one clamped retry, then
    /// the row's next appearance tries again.
    @Test func `retry delay is clamped at both ends`() {
        #expect(ImageCache.retryDelay(after: response(retryAfter: "60")) == 3)
        #expect(ImageCache.retryDelay(after: response(retryAfter: "0")) == 0.5)
        #expect(ImageCache.retryDelay(after: response(retryAfter: "-5")) == 0.5)
        #expect(ImageCache.retryDelay(after: response(retryAfter: "garbage")) == 1)
    }

    // MARK: - Load phase ordering
    //
    // Each progress callback used to spawn its own unstructured Task, one per
    // 256KB chunk, with no ordering between them — a late .downloading could
    // land after .preparing and rewind the label.

    @Test @MainActor func `phases rank in the order they occur`() {
        let ordered: [APIClient.LoadPhase?] = [
            nil,
            .readingCache,
            .connecting,
            .downloading(receivedBytes: 0, expectedBytes: nil),
            .preparing,
        ]
        let ranks = ordered.map(TrackerLoader.rank)
        #expect(ranks == ranks.sorted())
        #expect(Set(ranks).count == ranks.count, "each phase needs a distinct rank")
    }

    @Test @MainActor func `progress within a phase does not change its rank`() {
        let early = TrackerLoader.rank(.downloading(receivedBytes: 1, expectedBytes: 100))
        let late = TrackerLoader.rank(.downloading(receivedBytes: 99, expectedBytes: 100))
        #expect(early == late)
    }

    // MARK: - Connecting label escalation
    //
    // .connecting spans the whole of time-to-first-byte, which on a cold parse
    // is the backend fetching from Google and parsing. One static string for
    // all of it read as a hang.

    @Test func `the connecting label escalates with elapsed time`() {
        #expect(TrackerInputView.connectingLabel(elapsed: 0) == "Contacting server…")
        #expect(TrackerInputView.connectingLabel(elapsed: 1.0) == "Contacting server…")
        #expect(TrackerInputView.connectingLabel(elapsed: 2.0) == "Fetching tracker…")
        #expect(TrackerInputView.connectingLabel(elapsed: 4.9) == "Fetching tracker…")
        #expect(TrackerInputView.connectingLabel(elapsed: 30) == "Parsing a large tracker…")
    }

    @Test func `the label never goes backwards as time passes`() {
        var seen: [String] = []
        for tenths in 0...200 {
            let label = TrackerInputView.connectingLabel(elapsed: Double(tenths) / 10)
            if seen.last != label { seen.append(label) }
        }
        #expect(seen == ["Contacting server…", "Fetching tracker…", "Parsing a large tracker…"])
    }
}
