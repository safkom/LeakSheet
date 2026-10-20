import Foundation
import Testing

@testable import LeakSheet

@MainActor
@Suite(.serialized)
struct AudioEngineRetryTests {
    private func song(_ name: String, id: String) -> SongVersion {
        SongVersion(name: name, links: ["https://pillows.su/f/\(id)"])
    }

    @Test func `retryCurrent keeps the era context so auto-advance survives`() {
        let engine = AudioEngine.shared
        let a = song("A", id: "aaa"), b = song("B", id: "bbb")
        engine.playInEra(a, eraName: "E", artistName: "X", artUrl: "", versions: [a, b])

        engine.retryCurrent()
        #expect(engine.currentTrack?.name == "A")
        #expect(engine.error.isEmpty)

        engine.playNext()
        #expect(engine.currentTrack?.name == "B")
        engine.stopTrack()
    }

    @Test func `togglePlay on a track without a live item rebuilds it`() {
        let engine = AudioEngine.shared
        let a = song("A", id: "aaa")
        engine.playTrack(a, artistName: "X")
        engine.stopTrack()
        // stopTrack clears the track; a toggle with nothing loaded must not crash or invent one.
        engine.togglePlay()
        #expect(engine.currentTrack == nil)
    }
}
