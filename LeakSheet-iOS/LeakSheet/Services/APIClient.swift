import Foundation

/// HTTP client for the LeakSheet backend API.
actor APIClient {
    static let shared = APIClient()

    /// Production API base URL. The web app serves API under /api on the same domain.
    static let defaultBaseURL = "https://sheets.safko.eu/api"

    /// UserDefaults key for a custom backend URL set in Settings.
    static let baseURLDefaultsKey = "leaksheet_api_base_url"

    /// Active API base URL — a custom server from Settings, or the production default.
    static var baseURL: String {
        let custom = UserDefaults.standard.string(forKey: baseURLDefaultsKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !custom.isEmpty, custom.lowercased().hasPrefix("http"), URL(string: custom) != nil else {
            return defaultBaseURL
        }
        return custom.hasSuffix("/") ? String(custom.dropLast()) : custom
    }

    private static var sheetEndpoint: URL { makeEndpoint("sheet") }
    private static var cacheClearEndpoint: URL { makeEndpoint("cache/clear") }

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

    private init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 90
        config.httpAdditionalHeaders = [
            "Content-Type": "application/json",
            "Accept": "application/json",
        ]
        self.session = URLSession(configuration: config)

        self.decoder = JSONDecoder()
    }

    // MARK: - Parse Sheet

    struct ParseResult {
        let artist: Artist
        let etag: String?
        let unchanged: Bool
    }

    func parseSheet(
        url: String,
        artistName: String? = nil,
        useCache: Bool = true,
        forceRefresh: Bool = false,
        cachedEtag: String? = nil
    ) async throws -> ParseResult {
        var request = URLRequest(url: Self.sheetEndpoint)
        request.httpMethod = "POST"

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

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.httpError(status: 0, message: "Unexpected response type")
        }

        let etag = Self.normalizeETag(httpResponse.value(forHTTPHeaderField: "ETag"))

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

        let artist = try Self.decodeArtist(from: data)
        return ParseResult(artist: artist, etag: etag, unchanged: false)
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

    // MARK: - Stream URL

    nonisolated func streamURL(for originalLink: String) -> URL? {
        Self._streamURL(for: originalLink)
    }

    private nonisolated static func _streamURL(for originalLink: String) -> URL? {
        guard StreamResolver.isStreamableURL(originalLink),
              let encoded = originalLink.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed)
        else { return nil }
        return URL(string: "\(baseURL)/stream?url=\(encoded)")
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

    // MARK: - Clear Cache

    func clearCache() async throws -> Int {
        var request = URLRequest(url: Self.cacheClearEndpoint)
        request.httpMethod = "POST"

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.httpError(status: 0, message: "Unexpected response type")
        }

        guard httpResponse.statusCode == 200 else {
            throw APIError.httpError(status: httpResponse.statusCode, message: "Cache clear failed")
        }

        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let cleared = json["cleared"] as? Int {
            return cleared
        }
        return 0
    }
}

// MARK: - Errors

enum APIError: LocalizedError, Sendable {
    case invalidURL
    case notModified(etag: String?)
    case httpError(status: Int, message: String)
    case decodingError

    var errorDescription: String? {
        switch self {
        case .invalidURL: "Invalid URL"
        case .notModified: "Not modified"
        case .httpError(_, let message): message
        case .decodingError: "Failed to decode response"
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
    }
}
