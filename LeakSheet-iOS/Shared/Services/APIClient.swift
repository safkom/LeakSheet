import Foundation

/// HTTP client for the LeakSheet backend API.
actor APIClient {
    static let shared = APIClient()

    /// Production API base URL. The web app serves API under /api on the same domain.
    static let defaultBaseURL = "https://sheets.safko.eu/api"

    /// UserDefaults key for a custom backend URL set in Settings.
    static let baseURLDefaultsKey = "leaksheet_api_base_url"

    /// Active API base URL — a custom server from Settings, or the production
    /// default.
    ///
    /// Resolved once per change. This is read from `body` for every visible
    /// row that shows art (imageProxyURL), and it was doing a UserDefaults
    /// lookup, trim, lowercase, prefix check and URL validation on each one.
    ///
    /// The cache invalidates itself. Both Settings screens bind the key with
    /// `@AppStorage`, which writes UserDefaults directly and calls nothing —
    /// so an explicit invalidation call was never reached and a new server
    /// only took effect after a relaunch. Observing the store's own change
    /// notification is the version that cannot be forgotten at a call site.
    /// Read from `body` on the MainActor and from inside this actor, so the
    /// memo is lock-protected rather than `nonisolated(unsafe)` — the
    /// annotation silenced the Swift 6 diagnostic without removing the race.
    static var baseURL: String {
        _cacheLock.lock()
        defer { _cacheLock.unlock() }
        if let cached = _cachedBaseURL { return cached }
        let raw = UserDefaults.standard.string(forKey: baseURLDefaultsKey)
        let resolved = resolveBaseURL(raw)
        _cachedBaseURL = resolved
        _cachedRaw = .some(raw)
        return resolved
    }

    private nonisolated(unsafe) static var _cachedBaseURL: String?
    /// The raw defaults value `_cachedBaseURL` was resolved from. Outer nil:
    /// nothing resolved yet. Inner nil: the key was unset.
    private nonisolated(unsafe) static var _cachedRaw: String??
    private static let _cacheLock = NSLock()

    /// Drop the memo only if the base-URL key itself changed.
    ///
    /// `didChangeNotification` fires for ANY key. EraColorExtractor flushes its
    /// colour cache to defaults two seconds after every extraction burst —
    /// i.e. while the user scrolls, exactly when this memo is meant to spare a
    /// resolve per visible row — so invalidating on every notification threw
    /// it away at the worst moment.
    private static func invalidateIfBaseURLChanged() {
        let raw = UserDefaults.standard.string(forKey: baseURLDefaultsKey)
        _cacheLock.lock()
        if baseURLKeyChanged(cachedRaw: _cachedRaw, current: raw) {
            _cachedBaseURL = nil
            _cachedRaw = nil
        }
        _cacheLock.unlock()
    }

    /// Whether a defaults change touched the base-URL key. Nothing memoised yet
    /// (outer nil) means there is nothing to drop.
    static func baseURLKeyChanged(cachedRaw: String??, current: String?) -> Bool {
        guard let cachedRaw else { return false }
        return cachedRaw != current
    }

    private nonisolated(unsafe) static var _observer: NSObjectProtocol?

    /// Watch the defaults store for base-URL changes. Called once at launch.
    ///
    /// Both Settings screens bind the key with `@AppStorage`, which writes
    /// UserDefaults directly and calls nothing — so an explicit
    /// invalidation call at the write site was never reached, and a new
    /// custom server only took effect after a relaunch. Observing the store
    /// is the version that cannot be forgotten at a call site.
    @MainActor
    static func startObservingBaseURL() {
        guard _observer == nil else { return }
        _observer = NotificationCenter.default.addObserver(
            forName: UserDefaults.didChangeNotification,
            object: UserDefaults.standard,
            queue: nil
        ) { _ in invalidateIfBaseURLChanged() }
    }

    private static func resolveBaseURL(_ raw: String?) -> String {
        let custom = raw?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !custom.isEmpty, custom.lowercased().hasPrefix("http"), URL(string: custom) != nil else {
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

    private let session: URLSession
    private let decoder: JSONDecoder

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

        self.decoder = JSONDecoder()
    }

    // MARK: - Parse Sheet

    struct ParseResult {
        let artist: Artist
        /// Raw response bytes — cached verbatim so the disk copy always
        /// matches the server payload (no re-encode pass).
        let rawData: Data
        let etag: String?
        let unchanged: Bool
    }

    /// Cold-load progress for the landing screen. `expectedBytes` is the
    /// wire Content-Length when the server sent one (nil for chunked/gzip
    /// responses without it) — the UI shows a fraction when it's known and
    /// a byte counter otherwise.
    nonisolated enum LoadPhase: Equatable, Sendable {
        /// Reading the local ETag/payload. Cheap now that the ETag lives in a
        /// sidecar, but the 304 replay still decodes a multi-MB payload here.
        case readingCache
        case connecting
        /// What the server says it is doing during a cold parse, when it streams
        /// progress. `done`/`total` count the extra tabs being read.
        case server(message: String, done: Int?, total: Int?)
        case downloading(receivedBytes: Int64, expectedBytes: Int64?)
        /// Decoding the payload and building the artist view model. Used to be
        /// silent, which is most of why "Contacting server…" appeared to cover
        /// the whole load.
        case preparing
    }

    func parseSheet(
        url: String,
        artistName: String? = nil,
        useCache: Bool = true,
        forceRefresh: Bool = false,
        cachedEtag: String? = nil,
        onProgress: (@Sendable (LoadPhase) -> Void)? = nil
    ) async throws -> ParseResult {
        var request = URLRequest(url: Self.sheetEndpoint)
        request.httpMethod = "POST"
        // A cold parse can take many seconds; ask the server to narrate it.
        // Hits and 304s still come back as plain JSON, and a server that
        // predates the stream ignores this and sends JSON too.
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

        // A streamed cold parse reports its outcome in the body, not the
        // status line: the 200 was sent before the parse had finished.
        if let stream {
            if let failure = stream.failure {
                throw APIError.httpError(status: failure.status, message: failure.detail)
            }
            guard let streamedEtag = stream.etag else {
                throw APIError.httpError(
                    status: 0, message: "The server stopped before sending the tracker."
                )
            }
            etag = Self.normalizeETag(streamedEtag)
        }

        if httpResponse.statusCode == 304 {
            // 304 Not Modified — caller should use cached data
            throw APIError.notModified(etag: etag)
        }

        guard httpResponse.statusCode == 200 else {
            let detail = Self.decodeErrorResponse(from: data)
            throw APIError.httpError(
                status: httpResponse.statusCode,
                message: detail?.detail ?? "HTTP \(httpResponse.statusCode)"
            )
        }

        onProgress?(.preparing)
        let artist = try Self.decodeArtist(from: data)
        return ParseResult(artist: artist, rawData: data, etag: etag, unchanged: false)
    }

    /// How a streamed (NDJSON) cold parse ended.
    nonisolated struct StreamOutcome: Sendable {
        var etag: String?
        var failure: (status: Int, detail: String)?
    }

    /// Accumulates a response body from delegate chunk callbacks and reports
    /// throttled LoadPhase progress. URLSession serializes delegate calls,
    /// so the mutable state needs no locking (@unchecked Sendable).
    ///
    /// For a streamed cold parse it also splits the body: progress lines
    /// become `.server` phases until the artist header, and everything after
    /// that is the payload. A delegate rather than `data(for:)`, because the
    /// lines have to be acted on as they arrive.
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
            // gzip bodies decompress past the wire Content-Length — drop the
            // total rather than showing a >100% bar; the UI falls back to a
            // byte counter. (A stream's total is exact, so this never trips.)
            if let total = expected, Int64(data.count) > total { expected = nil }
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
                expected = bytes
                if let bytes { data.reserveCapacity(Int(bytes)) }
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

    // MARK: - Image Proxy

    /// Proxy URL for an art image. Pass `width` (a pixel bucket) to have the
    /// backend downscale — sized requests decode dramatically faster on
    /// device and cache better.
    nonisolated func imageProxyURL(for imageURL: String, width: Int? = nil) -> URL? {
        guard var components = URLComponents(string: "\(Self.baseURL)/image-proxy") else { return nil }
        var fullURL = imageURL
        if fullURL.hasPrefix("//") { fullURL = "https:" + fullURL }
        var items = [URLQueryItem(name: "url", value: fullURL)]
        if let width {
            items.append(URLQueryItem(name: "w", value: String(width)))
        }
        components.queryItems = items
        return components.url
    }

    // MARK: - Metadata

    /// Fetch stream file metadata (codec, bitrate, …) for a file-sharing link.
    /// Returns nil when the provider has no metadata API (e.g. krakenfiles) —
    /// callers fall back to player-derived format info.
    func fetchMetadata(for url: String) async throws -> FileMetadata? {
        guard var components = URLComponents(string: "\(Self.baseURL)/metadata") else {
            throw APIError.invalidURL
        }
        components.queryItems = [URLQueryItem(name: "url", value: url)]
        guard let requestURL = components.url else { throw APIError.invalidURL }

        let (data, response) = try await session.data(from: requestURL)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.httpError(status: 0, message: "Unexpected response type")
        }

        if httpResponse.statusCode == 404 {
            return nil
        }
        guard httpResponse.statusCode == 200 else {
            throw APIError.httpError(status: httpResponse.statusCode, message: "Metadata fetch failed")
        }

        return try Self.decodeMetadata(from: data)
    }

    private nonisolated static func decodeMetadata(from data: Data) throws -> FileMetadata {
        try JSONDecoder().decode(FileMetadata.self, from: data)
    }

    // MARK: - Trackers (discovery)

    /// Fetch the artist-tracker discovery list from the backend /trackers
    /// endpoint (TrackerHub sheet, server-cached).
    func fetchTrackers() async throws -> [DiscoveryArtist] {
        guard let url = URL(string: "\(Self.baseURL)/trackers") else {
            throw APIError.invalidURL
        }
        let (data, response) = try await session.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.httpError(status: 0, message: "Unexpected response type")
        }
        guard httpResponse.statusCode == 200 else {
            throw APIError.httpError(status: httpResponse.statusCode, message: "Tracker list fetch failed")
        }
        return try Self.decodeTrackers(from: data)
    }

    private nonisolated static func decodeTrackers(from data: Data) throws -> [DiscoveryArtist] {
        try JSONDecoder().decode([DiscoveryArtist].self, from: data)
    }

    /// Strip the optional `W/` weak prefix and surrounding quotes from an
    /// HTTP ETag header value, preserving inner content. Returns nil when the
    /// header is missing or empty.
    private nonisolated static func normalizeETag(_ raw: String?) -> String? {
        guard var value = raw, !value.isEmpty else { return nil }
        if value.hasPrefix("W/") { value.removeFirst(2) }
        return value.trimmingCharacters(in: CharacterSet(charactersIn: "\""))
    }

    private nonisolated static func decodeArtist(from data: Data) throws -> Artist {
        try JSONDecoder().decode(Artist.self, from: data)
    }

    private nonisolated static func decodeErrorResponse(from data: Data) -> ErrorResponse? {
        try? JSONDecoder().decode(ErrorResponse.self, from: data)
    }

}

// MARK: - Errors

enum APIError: LocalizedError, Sendable {
    case invalidURL
    case notModified(etag: String?)
    case httpError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: "Invalid URL"
        case .notModified: "Not modified"
        case .httpError(_, let message): message
        }
    }
}

nonisolated struct ErrorResponse: Codable, Sendable {
    let detail: String
}

// MARK: - FileMetadata

/// Stream file metadata from the backend /metadata endpoint. Field presence
/// varies by provider: pillows carries full format info, froste an estimated
/// bitrate analysis, imgur only file facts.
nonisolated struct FileMetadata: Codable, Sendable {
    let provider: String?
    let container: String?
    let codec: String?
    let codecProfile: String?
    let bitrate: String?
    let sampleRate: String?
    let bitsPerSample: String?
    let lossless: Bool?
    let channels: Int?
    let duration: String?
    let artist: String?
    let title: String?
    // froste analyze-quality
    let estimatedBitrate: Int?
    let frequencyCutoff: Double?
    let qualityMismatch: Bool?
    // imgur file API
    let fileSize: Int?
    let mimeType: String?
    let filename: String?
    /// Backend-derived "audio" | "video" | "unknown" — the only video signal
    /// for opaque stream-host URLs (pillows always reports audio/mp4).
    let mediaKind: String?

    enum CodingKeys: String, CodingKey {
        case provider, container, codec, bitrate, lossless, channels
        case duration, artist, title, filename
        case codecProfile = "codec_profile"
        case sampleRate = "sample_rate"
        case bitsPerSample = "bits_per_sample"
        case estimatedBitrate = "estimated_bitrate"
        case frequencyCutoff = "frequency_cutoff"
        case qualityMismatch = "quality_mismatch"
        case fileSize = "file_size"
        case mimeType = "mime_type"
        case mediaKind = "media_kind"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        provider = try c.decodeIfPresent(String.self, forKey: .provider)
        container = try c.decodeIfPresent(String.self, forKey: .container)
        codec = try c.decodeIfPresent(String.self, forKey: .codec)
        codecProfile = try c.decodeIfPresent(String.self, forKey: .codecProfile)
        bitrate = try c.decodeIfPresent(String.self, forKey: .bitrate)
        sampleRate = try c.decodeIfPresent(String.self, forKey: .sampleRate)
        bitsPerSample = try c.decodeIfPresent(String.self, forKey: .bitsPerSample)
        lossless = try c.decodeIfPresent(Bool.self, forKey: .lossless)
        // Backend emits channels as Int when numeric, String otherwise.
        if let numeric = try? c.decodeIfPresent(Int.self, forKey: .channels) {
            channels = numeric
        } else if let text = try? c.decodeIfPresent(String.self, forKey: .channels) {
            channels = Int(text)
        } else {
            channels = nil
        }
        duration = try c.decodeIfPresent(String.self, forKey: .duration)
        artist = try c.decodeIfPresent(String.self, forKey: .artist)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        estimatedBitrate = try c.decodeIfPresent(Int.self, forKey: .estimatedBitrate)
        frequencyCutoff = try c.decodeIfPresent(Double.self, forKey: .frequencyCutoff)
        qualityMismatch = try c.decodeIfPresent(Bool.self, forKey: .qualityMismatch)
        fileSize = try c.decodeIfPresent(Int.self, forKey: .fileSize)
        mimeType = try c.decodeIfPresent(String.self, forKey: .mimeType)
        filename = try c.decodeIfPresent(String.self, forKey: .filename)
        mediaKind = try c.decodeIfPresent(String.self, forKey: .mediaKind)
    }
}
