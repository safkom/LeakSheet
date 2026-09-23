import Foundation

/// Splits a streamed cold parse from POST /sheet into events and payload.
///
/// The server sends one JSON object per line — progress, then an artist
/// header — followed by the artist JSON itself as raw bytes. Network chunks
/// cut lines anywhere, so lines are buffered until their newline arrives.
/// Once the header has been read, every later byte is payload and is handed
/// straight back without scanning: that part is megabytes.
nonisolated struct ProgressStreamReader {
    static let mimeType = "application/x-ndjson"

    enum Event: Equatable, Sendable {
        case progress(message: String, done: Int?, total: Int?)
        /// The payload follows. `bytes` is its exact decoded size.
        case artist(etag: String, bytes: Int64?)
        case failure(status: Int, detail: String)
    }

    /// Longer than any progress or header line. A buffer past this without a
    /// newline is the payload behind a header this client could not read.
    static let maxLineBytes = 64 * 1024

    private var buffer = Data()
    private(set) var inPayload = false
    private var failed = false

    /// Consume one network chunk. Returns the events completed by it, and any
    /// payload bytes it carried.
    mutating func feed(_ chunk: Data) -> (events: [Event], payload: Data) {
        if inPayload { return ([], chunk) }
        if failed { return ([], Data()) }
        buffer.append(chunk)
        var events: [Event] = []
        while let newline = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<newline]
            let rest = buffer[buffer.index(after: newline)...]
            if let event = Self.decode(line) {
                events.append(event)
                if case .artist = event {
                    inPayload = true
                    let payload = Data(rest)
                    buffer = Data()
                    return (events, payload)
                }
            }
            buffer = Data(rest)
        }
        if buffer.count > Self.maxLineBytes {
            // Stop rescanning megabytes of unreadable payload for a newline.
            // ponytail: the rest of the body still downloads and is dropped.
            buffer = Data()
            failed = true
            events.append(.failure(
                status: 0, detail: "The server sent a response this version of the app can't read."
            ))
        }
        return (events, Data())
    }

    private struct Line: Decodable {
        let type: String
        let message: String?
        let done: Int?
        let total: Int?
        let etag: String?
        let bytes: Int64?
        let status: Int?
        let detail: String?
    }

    /// Nil for a blank or unrecognised line, so a newer server can add event
    /// types without breaking this client.
    private static func decode(_ line: Data) -> Event? {
        guard let parsed = try? JSONDecoder().decode(Line.self, from: line) else { return nil }
        switch parsed.type {
        case "progress":
            guard let message = parsed.message else { return nil }
            return .progress(message: message, done: parsed.done, total: parsed.total)
        case "artist":
            guard let etag = parsed.etag else { return nil }
            return .artist(etag: etag, bytes: parsed.bytes)
        case "error":
            return .failure(
                status: parsed.status ?? 0,
                detail: parsed.detail ?? "The server could not load this tracker."
            )
        default:
            return nil
        }
    }
}
