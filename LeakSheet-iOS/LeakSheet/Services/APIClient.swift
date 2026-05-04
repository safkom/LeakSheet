import Foundation

/// HTTP client for the LeakSheet backend API.
actor APIClient {
    static let shared = APIClient()

    /// Production API base URL. The web app serves API under /api on the same domain.
    /// Update this to your production hostname.
    static let baseURL = "https://sheets.safko.eu/api"

    // Hoisted endpoint constants. Built from a known-good base URL; if a
    // future edit breaks them we want a clear, descriptive crash here rather
    // than at the first network call.
    private static let sheetEndpoint: URL = makeEndpoint("sheet")
    private static let cacheClearEndpoint: URL = makeEndpoint("cache/clear")

    private static func makeEndpoint(_ path: String) -> URL {
        guard let url = URL(string: "\(baseURL)/\(path)") else {
            fatalError("APIClient: invalid endpoint URL '\(baseURL)/\(path)'")
        }
        return url
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

    nonisolated func imageProxyURL(for imageURL: String) -> URL? {
        guard var components = URLComponents(string: "\(Self.baseURL)/image-proxy") else { return nil }
        var fullURL = imageURL
        if fullURL.hasPrefix("//") { fullURL = "https:" + fullURL }
        components.queryItems = [URLQueryItem(name: "url", value: fullURL)]
        return components.url
    }

    // MARK: - Metadata

    func fetchMetadata(for url: String) async throws -> [String: Any] {
        guard var components = URLComponents(string: "\(Self.baseURL)/metadata") else {
            throw APIError.invalidURL
        }
        components.queryItems = [URLQueryItem(name: "url", value: url)]
        guard let requestURL = components.url else { throw APIError.invalidURL }

        let (data, response) = try await session.data(from: requestURL)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.httpError(status: 0, message: "Unexpected response type")
        }

        guard httpResponse.statusCode == 200 else {
            throw APIError.httpError(status: httpResponse.statusCode, message: "Metadata fetch failed")
        }

        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw APIError.decodingError
        }
        return json
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
