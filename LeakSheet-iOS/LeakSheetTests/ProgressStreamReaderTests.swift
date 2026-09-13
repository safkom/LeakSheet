import Foundation
import Testing

@testable import LeakSheet

/// The streamed cold parse from POST /sheet: progress lines, an artist
/// header, then the artist JSON. Network chunks split it anywhere.
struct ProgressStreamReaderTests {
    private static let payload = Data(#"{"name":"Test","slug":"test","eras":[]}"#.utf8)

    private static let stream: Data = {
        var d = Data()
        d.append(Data(#"{"type":"progress","stage":"fetching","message":"Found 19 tabs — downloading Unreleased"}"#.utf8))
        d.append(0x0A)
        d.append(Data(#"{"type":"progress","stage":"tabs","message":"Read Misc","done":2,"total":9}"#.utf8))
        d.append(0x0A)
        d.append(Data(#"{"type":"artist","etag":"8c6f587cdeec162e","bytes":40}"#.utf8))
        d.append(0x0A)
        d.append(payload)
        d.append(0x0A)
        return d
    }()

    private static let expectedEvents: [ProgressStreamReader.Event] = [
        .progress(message: "Found 19 tabs — downloading Unreleased", done: nil, total: nil),
        .progress(message: "Read Misc", done: 2, total: 9),
        .artist(etag: "8c6f587cdeec162e", bytes: 40),
    ]

    private static func read(_ chunks: [Data]) -> ([ProgressStreamReader.Event], Data) {
        var reader = ProgressStreamReader()
        var events: [ProgressStreamReader.Event] = []
        var payload = Data()
        for chunk in chunks {
            let (e, p) = reader.feed(chunk)
            events += e
            payload.append(p)
        }
        return (events, payload)
    }

    @Test func `one chunk yields every event and the payload`() {
        let (events, payload) = Self.read([Self.stream])
        #expect(events == Self.expectedEvents)
        #expect(payload == Self.payload + Data([0x0A]))
    }

    /// Every split point, including inside the multi-byte "—" and exactly on a
    /// newline, must decode to the same events and bytes.
    @Test func `any split into two chunks gives the same result`() {
        for cut in 1..<Self.stream.count {
            let (events, payload) = Self.read([
                Self.stream.prefix(cut), Self.stream.suffix(from: cut),
            ])
            #expect(events == Self.expectedEvents, "split at \(cut)")
            #expect(payload == Self.payload + Data([0x0A]), "split at \(cut)")
        }
    }

    @Test func `byte-at-a-time delivery still works`() {
        let (events, payload) = Self.read(Self.stream.map { Data([$0]) })
        #expect(events == Self.expectedEvents)
        #expect(payload == Self.payload + Data([0x0A]))
    }

    @Test func `an error line ends the stream as a failure`() {
        let line = Data(#"{"type":"error","status":403,"detail":"This tracker is private or has been taken down."}"#.utf8) + Data([0x0A])
        let (events, payload) = Self.read([line])
        #expect(events == [.failure(status: 403, detail: "This tracker is private or has been taken down.")])
        #expect(payload.isEmpty)
    }

    @Test func `unknown event types are skipped, not fatal`() {
        let line = Data(#"{"type":"hint","message":"from a newer server"}"#.utf8) + Data([0x0A])
        let (events, _) = Self.read([line, Self.stream])
        #expect(events == Self.expectedEvents)
    }
}
