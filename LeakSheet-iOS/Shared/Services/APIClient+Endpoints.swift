import Foundation

extension APIClient {
    // MARK: - Image Proxy

    /// Proxy URL for an art image. Pass `width` (a pixel bucket) to have the backend
    /// downscale; sized requests decode faster on device and cache better.
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
    /// endpoint (ArtistGrid registry, server-cached).
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

    // MARK: - Stream host health

    /// Each streaming provider's status, as the backend sees it (`GET /hosts`).
    func fetchHostHealth() async throws -> [HostStatus] {
        guard let url = URL(string: "\(Self.baseURL)/hosts") else {
            throw APIError.invalidURL
        }
        let (data, response) = try await session.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.httpError(status: 0, message: "Unexpected response type")
        }
        guard httpResponse.statusCode == 200 else {
            throw APIError.httpError(status: httpResponse.statusCode, message: "Host status fetch failed")
        }
        return try Self.decodeHostHealth(from: data)
    }

    nonisolated static func decodeHostHealth(from data: Data) throws -> [HostStatus] {
        try JSONDecoder().decode(HostHealthResponse.self, from: data).hosts
    }

    /// Strip the optional `W/` weak prefix and surrounding quotes from an
    /// HTTP ETag header value, preserving inner content. Returns nil when the
    /// header is missing or empty.
    nonisolated static func normalizeETag(_ raw: String?) -> String? {
        guard var value = raw, !value.isEmpty else { return nil }
        if value.hasPrefix("W/") { value.removeFirst(2) }
        return value.trimmingCharacters(in: CharacterSet(charactersIn: "\""))
    }

    nonisolated static func decodeArtist(from data: Data) throws -> Artist {
        try JSONDecoder().decode(Artist.self, from: data)
    }

    /// The message for a failure whose body carried no `detail`.
    nonisolated static func bareStatusMessage(_ status: Int) -> String {
        "HTTP \(status)"
    }

    nonisolated static func decodeErrorResponse(from data: Data) -> ErrorResponse? {
        try? JSONDecoder().decode(ErrorResponse.self, from: data)
    }
}
