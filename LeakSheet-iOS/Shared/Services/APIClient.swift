import Foundation

/// HTTP client for the LeakSheet backend API.
actor APIClient {
    static let shared = APIClient()

    /// Production API base URL. The web app serves API under /api on the same domain.
    static let defaultBaseURL = "https://sheets.safko.eu/api"

    /// UserDefaults key for a custom backend URL set in Settings.
    static let baseURLDefaultsKey = "leaksheet_api_base_url"

    /// Active API base URL — a custom server from Settings, or the production
    /// default. Read fresh each time: UserDefaults already serves it from memory.
    static var baseURL: String {
        resolveBaseURL(UserDefaults.standard.string(forKey: baseURLDefaultsKey))
    }

    /// An explicit http(s) scheme and a non-empty host: "httpfoo" or "http://" are not servers.
    static func isValidServerURL(_ raw: String) -> Bool {
        guard let url = URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https"
        else { return false }
        return !(url.host() ?? "").isEmpty
    }

    static func resolveBaseURL(_ raw: String?) -> String {
        let custom = raw?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard isValidServerURL(custom) else {
            return defaultBaseURL
        }
        return custom.hasSuffix("/") ? String(custom.dropLast()) : custom
    }

    private static var sheetEndpoint: URL { makeEndpoint("sheet") }

    private static func makeEndpoint(_ path: String) -> URL {
        if let url = URL(string: "\(baseURL)/\(path)") {
            return url
        }
        // Custom base URL produced an invalid endpoint — fall back to the
        // known-good production URL rather than crashing.
        return URL(string: "\(defaultBaseURL)/\(path)")!
    }

    let session: URLSession

    /// Pass a session (e.g. URLProtocol-stubbed) for tests; nil builds the
    /// production configuration.
    init(session: URLSession? = nil) {
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 90
            config.httpAdditionalHeaders = [
                "Content-Type": "application/json",
                "Accept": "application/json",
            ]
            self.session = URLSession(configuration: config)
        }
    }

    // MARK: - Parse Sheet

    struct ParseResult {
        let artist: Artist
        /// Raw response bytes — cached verbatim so the disk copy always
        /// matches the server payload (no re-encode pass).
        let rawData: Data
        let etag: String?
    }

    /// Cold-load progress for the landing screen. `expectedBytes` is the wire
    /// Content-Length when sent (nil for chunked/gzip): a fraction if known, else a byte counter.
    nonisolated enum LoadPhase: Equatable, Sendable {
        /// Reading the local ETag/payload; the 304 replay decodes a multi-MB payload here.
        case readingCache
        case connecting
        /// What the server says it is doing during a cold parse, when it streams
        /// progress. `done`/`total` count the extra tabs being read.
        case server(message: String, done: Int?, total: Int?)
        case downloading(receivedBytes: Int64, expectedBytes: Int64?)
        /// Decoding the payload and building the artist view model.
        case preparing
    }

    private static func sheetRequest(
        url: String, artistName: String?, useCache: Bool, forceRefresh: Bool, cachedEtag: String?
    ) throws -> URLRequest {
        var request = URLRequest(url: sheetEndpoint)
        request.httpMethod = "POST"
        // A cold parse can take many seconds; ask the server to narrate it. Hits, 304s
        // and older servers still answer with plain JSON.
        request.setValue("application/x-ndjson, application/json", forHTTPHeaderField: "Accept")
        if let etag = cachedEtag, !forceRefresh {
            request.setValue("\"\(etag)\"", forHTTPHeaderField: "If-None-Match")
        }
        let body: [String: Any] = [
            "url": url,
            "artist_name": artistName as Any,
            "use_cache": useCache,
            "force_refresh": forceRefresh,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return request
    }

    /// The ETag a streamed cold parse ends with. It reports its outcome in the body, not
    /// the status line: the 200 was sent before the parse had finished.
    private static func streamedEtag(_ stream: StreamOutcome, received: Int) throws -> String? {
        if let failure = stream.failure {
            throw APIError.httpError(status: failure.status, message: failure.detail)
        }
        guard let streamedEtag = stream.etag else {
            throw APIError.httpError(status: 0, message: "The server stopped before sending the tracker.")
        }
        // A proxy closing the connection cleanly mid-payload ends the task without an
        // error; catch the truncation here rather than as a JSON decoding failure.
        if let bytes = stream.bytes, Int64(received) != bytes {
            throw APIError.httpError(
                status: 0, message: "The download was cut off before the tracker finished. Try again."
            )
        }
        return normalizeETag(streamedEtag)
    }

    func parseSheet(
        url: String,
        artistName: String? = nil,
        useCache: Bool = true,
        forceRefresh: Bool = false,
        cachedEtag: String? = nil,
        onProgress: (@Sendable (LoadPhase) -> Void)? = nil
    ) async throws -> ParseResult {
        let request = try Self.sheetRequest(
            url: url, artistName: artistName, useCache: useCache, forceRefresh: forceRefresh, cachedEtag: cachedEtag
        )
        onProgress?(.connecting)
        // Chunked delegate download — see DECISIONS.md::APIClient.swift::chunked-download
        let downloadTask = session.dataTask(with: request)
        let (data, response, stream) = try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation {
                (continuation: CheckedContinuation<(Data, URLResponse, StreamOutcome?), Error>) in
                downloadTask.delegate = ChunkedDownloadDelegate(
                    onProgress: onProgress, continuation: continuation
                )
                downloadTask.resume()
            }
        } onCancel: {
            downloadTask.cancel()
        }
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.httpError(status: 0, message: "Unexpected response type")
        }

        var etag = Self.normalizeETag(httpResponse.value(forHTTPHeaderField: "ETag"))
        if let stream {
            etag = try Self.streamedEtag(stream, received: data.count)
        }

        if httpResponse.statusCode == 304 {
            // 304 Not Modified — caller should use cached data
            throw APIError.notModified(etag: etag)
        }

        guard httpResponse.statusCode == 200 else {
            let detail = Self.decodeErrorResponse(from: data)
            throw APIError.httpError(
                status: httpResponse.statusCode,
                message: detail?.detail ?? Self.bareStatusMessage(httpResponse.statusCode)
            )
        }

        onProgress?(.preparing)
        let artist = try Self.decodeArtist(from: data)
        return ParseResult(artist: artist, rawData: data, etag: etag)
    }

    /// How a streamed (NDJSON) cold parse ended.
    nonisolated struct StreamOutcome: Sendable {
        var etag: String?
        /// The payload size the header promised, to catch a truncated body.
        var bytes: Int64?
        var failure: (status: Int, detail: String)?
    }

    /// Accumulates a response body from delegate chunk callbacks and reports throttled
    /// LoadPhase progress. URLSession serializes delegate calls, so no locking is needed.
    ///
    /// For a streamed cold parse it also splits the body: progress lines become
    /// `.server` phases until the artist header; everything after is the payload.
    private nonisolated final class ChunkedDownloadDelegate: NSObject, URLSessionDataDelegate, @unchecked Sendable {
        private let onProgress: (@Sendable (LoadPhase) -> Void)?
        private let continuation: CheckedContinuation<(Data, URLResponse, StreamOutcome?), Error>
        private var data = Data()
        private var response: URLResponse?
        private var expected: Int64?
        private var lastReport = 0
        private var finished = false
        private var reader: ProgressStreamReader?
        private var outcome = StreamOutcome()

        init(
            onProgress: (@Sendable (LoadPhase) -> Void)?,
            continuation: CheckedContinuation<(Data, URLResponse, StreamOutcome?), Error>
        ) {
            self.onProgress = onProgress
            self.continuation = continuation
        }

        func urlSession(
            _ session: URLSession,
            dataTask: URLSessionDataTask,
            didReceive response: URLResponse,
            completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
        ) {
            self.response = response
            if response.mimeType == ProgressStreamReader.mimeType {
                // The wire length (if any) covers progress lines too; the real
                // payload size arrives in the artist header.
                reader = ProgressStreamReader()
            } else {
                let length = response.expectedContentLength
                expected = length > 0 ? length : nil
                if let expected { data.reserveCapacity(Int(expected)) }
            }
            completionHandler(.allow)
        }

        func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive chunk: Data) {
            if reader != nil {
                let (events, payload) = reader!.feed(chunk)
                for event in events { handle(event) }
                guard !payload.isEmpty else { return }
                data.append(payload)
            } else {
                data.append(chunk)
            }
            // gzip bodies decompress past the wire Content-Length: drop the total rather than
            // show >100%. A stream's total is exact (plus the payload's trailing newline).
            if reader == nil, let total = expected, Int64(data.count) > total { expected = nil }
            if data.count - lastReport >= 262_144 {
                lastReport = data.count
                onProgress?(.downloading(receivedBytes: Int64(data.count), expectedBytes: expected))
            }
        }

        private func handle(_ event: ProgressStreamReader.Event) {
            switch event {
            case .progress(let message, let done, let total):
                onProgress?(.server(message: message, done: done, total: total))
            case .artist(let etag, let bytes):
                outcome.etag = etag
                outcome.bytes = bytes
                expected = bytes
                // +1 for the payload line's newline, or the last append
                // reallocates the whole multi-MB buffer.
                if let bytes { data.reserveCapacity(Int(bytes) + 1) }
                onProgress?(.downloading(receivedBytes: 0, expectedBytes: bytes))
            case .failure(let status, let detail):
                outcome.failure = (status, detail)
            }
        }

        func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
            guard !finished else { return }
            finished = true
            if let error {
                continuation.resume(throwing: error)
            } else if let response {
                if reader != nil, data.last == 0x0A {
                    data.removeLast()  // the payload line's terminator
                }
                onProgress?(.downloading(receivedBytes: Int64(data.count), expectedBytes: expected))
                continuation.resume(returning: (data, response, reader == nil ? nil : outcome))
            } else {
                continuation.resume(throwing: URLError(.badServerResponse))
            }
        }
    }

}

// MARK: - Errors

// MARK: - FileMetadata
