import Foundation
import Testing

@testable import LeakSheet

/// APIClient networking tests via a URLProtocol stub — the ETag/304 flow,
/// raw-data threading, and cold-load progress events.
///
/// Serialized: every test swaps the shared `StubProtocol.handler`, so
/// parallel execution would race on it.
@Suite(.serialized)
struct APIClientTests {
    /// URLProtocol stub: each test registers a handler keyed by request.
    nonisolated final class StubProtocol: URLProtocol {
        nonisolated(unsafe) static var handler: (@Sendable (URLRequest) -> (HTTPURLResponse, Data))?

        override class func canInit(with request: URLRequest) -> Bool { true }
        override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

        override func startLoading() {
            guard let handler = Self.handler else { return }
            let (response, data) = handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        }

        override func stopLoading() {}
    }

    private func makeClient() -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        return APIClient(session: URLSession(configuration: config))
    }

    private nonisolated static let artistBody = Data(#"{"name": "Test", "slug": "test", "eras": []}"#.utf8)

    private nonisolated static func response(
        _ status: Int, headers: [String: String] = [:], url: URL
    ) -> HTTPURLResponse {
        HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
    }

    @Test func `200 returns artist with raw data and normalized etag`() async throws {
        StubProtocol.handler = { req in
            (Self.response(200, headers: ["ETag": "W/\"abc123\""], url: req.url!), Self.artistBody)
        }
        let result = try await makeClient().parseSheet(url: "https://docs.google.com/spreadsheets/d/x")
        #expect(result.artist.slug == "test")
        #expect(result.rawData == Self.artistBody)
        #expect(result.etag == "abc123")
    }

    @Test func `304 throws notModified with etag`() async throws {
        StubProtocol.handler = { req in
            (Self.response(304, headers: ["ETag": "\"abc123\""], url: req.url!), Data())
        }
        await #expect(throws: APIError.self) {
            _ = try await makeClient().parseSheet(
                url: "https://docs.google.com/spreadsheets/d/x", cachedEtag: "abc123"
            )
        }
    }

    @Test func `cached etag is sent as If-None-Match`() async throws {
        nonisolated(unsafe) var seenHeader: String?
        StubProtocol.handler = { req in
            seenHeader = req.value(forHTTPHeaderField: "If-None-Match")
            return (Self.response(200, url: req.url!), Self.artistBody)
        }
        _ = try await makeClient().parseSheet(
            url: "https://docs.google.com/spreadsheets/d/x", cachedEtag: "abc123"
        )
        #expect(seenHeader == "\"abc123\"")
    }

    @Test func `force refresh skips If-None-Match`() async throws {
        nonisolated(unsafe) var seenHeader: String? = "sentinel"
        StubProtocol.handler = { req in
            seenHeader = req.value(forHTTPHeaderField: "If-None-Match")
            return (Self.response(200, url: req.url!), Self.artistBody)
        }
        _ = try await makeClient().parseSheet(
            url: "https://docs.google.com/spreadsheets/d/x", forceRefresh: true, cachedEtag: "abc123"
        )
        #expect(seenHeader == nil)
    }

    @Test func `progress reports downloading then preparing`() async throws {
        StubProtocol.handler = { req in
            (Self.response(200, url: req.url!), Self.artistBody)
        }
        let recorder = ProgressRecorder()
        _ = try await makeClient().parseSheet(
            url: "https://docs.google.com/spreadsheets/d/x",
            onProgress: { phase in Task { await recorder.record(phase) } }
        )
        // Give the detached recorder tasks a beat to land.
        try await Task.sleep(for: .milliseconds(50))
        let phases = await recorder.phases
        #expect(phases.contains { if case .downloading = $0 { return true }; return false })
        #expect(phases.last == .preparing)
    }
}

extension APIClientTests {
    private nonisolated static func ndjson(_ lines: [String], payload: Data? = nil) -> Data {
        var d = Data()
        for line in lines { d.append(Data(line.utf8)); d.append(0x0A) }
        if let payload { d.append(payload); d.append(0x0A) }
        return d
    }

    @Test func `a streamed cold parse reports server progress and returns the artist`() async throws {
        let body = Self.ndjson([
            #"{"type":"progress","stage":"parsing","message":"Parsing Unreleased (11.8 MB)"}"#,
            #"{"type":"progress","stage":"tabs","message":"Read Misc","done":2,"total":9}"#,
            #"{"type":"artist","etag":"8c6f587cdeec162e","bytes":\#(Self.artistBody.count)}"#,
        ], payload: Self.artistBody)
        nonisolated(unsafe) var accept: String?
        StubProtocol.handler = { req in
            accept = req.value(forHTTPHeaderField: "Accept")
            return (Self.response(200, headers: ["Content-Type": "application/x-ndjson"], url: req.url!), body)
        }
        let recorder = ProgressRecorder()
        let result = try await makeClient().parseSheet(
            url: "https://docs.google.com/spreadsheets/d/x",
            onProgress: { phase in Task { await recorder.record(phase) } }
        )
        try await Task.sleep(for: .milliseconds(50))
        let phases = await recorder.phases

        #expect(accept?.contains("application/x-ndjson") == true)
        #expect(result.artist.slug == "test")
        // The payload's terminating newline is not part of the artist bytes,
        // which are cached verbatim.
        #expect(result.rawData == Self.artistBody)
        #expect(result.etag == "8c6f587cdeec162e")
        #expect(phases.contains(.server(message: "Parsing Unreleased (11.8 MB)", done: nil, total: nil)))
        #expect(phases.contains(.server(message: "Read Misc", done: 2, total: 9)))
    }

    @Test func `a streamed failure throws the server's status and message`() async throws {
        let body = Self.ndjson([
            #"{"type":"progress","stage":"fetching","message":"Opening the tracker"}"#,
            #"{"type":"error","status":403,"detail":"This tracker is private or has been taken down."}"#,
        ])
        StubProtocol.handler = { req in
            (Self.response(200, headers: ["Content-Type": "application/x-ndjson"], url: req.url!), body)
        }
        do {
            _ = try await makeClient().parseSheet(url: "https://docs.google.com/spreadsheets/d/x")
            Issue.record("expected the stream's error to throw")
        } catch let APIError.httpError(status, message) {
            #expect(status == 403)
            #expect(message == "This tracker is private or has been taken down.")
        }
    }

    @Test func `a stream that ends before the artist is an error, not an empty tracker`() async throws {
        let body = Self.ndjson([#"{"type":"progress","stage":"fetching","message":"Opening the tracker"}"#])
        StubProtocol.handler = { req in
            (Self.response(200, headers: ["Content-Type": "application/x-ndjson"], url: req.url!), body)
        }
        await #expect(throws: APIError.self) {
            _ = try await makeClient().parseSheet(url: "https://docs.google.com/spreadsheets/d/x")
        }
    }
}

private actor ProgressRecorder {
    var phases: [APIClient.LoadPhase] = []
    func record(_ phase: APIClient.LoadPhase) { phases.append(phase) }
}

struct BaseURLMemoTests {
    // didChangeNotification fires for every key; the base-URL memo must only
    // drop when its own key moved, or the era-colour cache flush during scroll
    // throws it away on every burst.
    @Test func `a write to another key keeps the memo`() {
        #expect(!APIClient.baseURLKeyChanged(cachedRaw: .some("https://a.example/api"), current: "https://a.example/api"))
        #expect(!APIClient.baseURLKeyChanged(cachedRaw: .some(nil), current: nil))
    }

    @Test func `setting, changing or clearing the key drops it`() {
        #expect(APIClient.baseURLKeyChanged(cachedRaw: .some(nil), current: "https://a.example/api"))
        #expect(APIClient.baseURLKeyChanged(cachedRaw: .some("https://a.example/api"), current: "https://b.example/api"))
        #expect(APIClient.baseURLKeyChanged(cachedRaw: .some("https://a.example/api"), current: nil))
    }

    @Test func `nothing memoised means nothing to drop`() {
        #expect(!APIClient.baseURLKeyChanged(cachedRaw: nil, current: "https://a.example/api"))
    }
}
