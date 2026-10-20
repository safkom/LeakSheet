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

    @Test func `retryCurrent replaces the player item`() throws {
        let engine = AudioEngine.shared
        engine.playTrack(song("A", id: "aaa"), artistName: "X")
        let first = try #require(engine.currentPlayer?.currentItem)

        engine.retryCurrent()
        let second = try #require(engine.currentPlayer?.currentItem)
        #expect(first !== second)
        engine.stopTrack()
    }

    @Test func `retryCurrent without a track does nothing`() {
        let engine = AudioEngine.shared
        engine.stopTrack()
        engine.retryCurrent()
        engine.resumePlayback()
        #expect(engine.currentTrack == nil)
    }
}
