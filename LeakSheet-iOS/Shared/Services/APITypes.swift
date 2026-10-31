import Foundation

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

/// One provider's row in `GET /hosts`.
nonisolated struct HostStatus: Codable, Sendable, Equatable {
    let provider: String
    let host: String
    let status: String

    var isDown: Bool { status == "down" }
}

nonisolated struct HostHealthResponse: Codable, Sendable {
    let hosts: [HostStatus]
}

nonisolated struct ErrorResponse: Codable, Sendable {
    let detail: String
}

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
        case duration, filename
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
        let values = try decoder.container(keyedBy: CodingKeys.self)
        provider = try values.decodeIfPresent(String.self, forKey: .provider)
        container = try values.decodeIfPresent(String.self, forKey: .container)
        codec = try values.decodeIfPresent(String.self, forKey: .codec)
        codecProfile = try values.decodeIfPresent(String.self, forKey: .codecProfile)
        bitrate = try values.decodeIfPresent(String.self, forKey: .bitrate)
        sampleRate = try values.decodeIfPresent(String.self, forKey: .sampleRate)
        bitsPerSample = try values.decodeIfPresent(String.self, forKey: .bitsPerSample)
        lossless = try values.decodeIfPresent(Bool.self, forKey: .lossless)
        // Backend emits channels as Int when numeric, String otherwise.
        if let numeric = try? values.decodeIfPresent(Int.self, forKey: .channels) {
            channels = numeric
        } else if let text = try? values.decodeIfPresent(String.self, forKey: .channels) {
            channels = Int(text)
        } else {
            channels = nil
        }
        duration = try values.decodeIfPresent(String.self, forKey: .duration)
        estimatedBitrate = try values.decodeIfPresent(Int.self, forKey: .estimatedBitrate)
        frequencyCutoff = try values.decodeIfPresent(Double.self, forKey: .frequencyCutoff)
        qualityMismatch = try values.decodeIfPresent(Bool.self, forKey: .qualityMismatch)
        fileSize = try values.decodeIfPresent(Int.self, forKey: .fileSize)
        mimeType = try values.decodeIfPresent(String.self, forKey: .mimeType)
        filename = try values.decodeIfPresent(String.self, forKey: .filename)
        mediaKind = try values.decodeIfPresent(String.self, forKey: .mediaKind)
    }
}
