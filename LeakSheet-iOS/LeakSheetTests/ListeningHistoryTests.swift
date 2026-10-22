import Foundation
import Testing

@testable import LeakSheet

private func version(_ name: String, tag: String? = nil, link: String? = nil) -> SongVersion {
    SongVersion(
        name: name, versionTag: tag, badge: nil, featuring: nil, producers: nil,
        collaboration: nil, refs: nil, director: nil, creditedArtists: nil, altTitles: nil, notes: nil, ogFilename: nil,
        ogFilenames: nil, samples: nil, trackLength: nil, fileDate: nil, leakDate: nil, previewDate: nil,
        availableLength: nil, quality: nil, streaming: nil, links: link.map { [$0] }, dateOfRecording: nil, type: nil, sources: nil, rating: nil
    )
}

/// A history backed by a unique temp file and its own defaults suite, so tests never share state.
@MainActor
private func makeHistory(enabled: Bool = true) -> (ListeningHistory, URL) {
    let file = FileManager.default.temporaryDirectory
        .appendingPathComponent("listening-\(UUID().uuidString).json")
    let suite = UserDefaults(suiteName: "listening-\(UUID().uuidString)")!
    suite.set(enabled, forKey: ListeningHistory.enabledKey)
    return (ListeningHistory(fileURL: file, defaults: suite), file)
}

struct PlayThresholdTests {
    @Test(arguments: [
        (29.0, 0.0, false),   // unknown duration: 29 s is short of 30
        (30.0, 0.0, true),    // unknown duration: 30 s reaches it
        (19.0, 40.0, false),  // 50% of 40 s is 20 s, and 19 s is short
        (20.0, 40.0, true),   // exactly 50% of a short track
        (29.0, 200.0, false), // long track: 29 s is short of the 30 s floor
        (30.0, 200.0, true),
    ] as [(TimeInterval, TimeInterval, Bool)])
    func `reaches at 30 seconds or half the duration`(
        listened: TimeInterval, duration: TimeInterval, expected: Bool
    ) {
        #expect(PlayThreshold.reached(listened: listened, duration: duration) == expected)
    }
}

@MainActor
struct ListeningHistoryTests {
    @Test func `increments the count and moves last forward`() {
        let (history, _) = makeHistory()
        let song = version("Hurricane", tag: "V4")
        let first = Date(timeIntervalSince1970: 1_000)
        let second = Date(timeIntervalSince1970: 2_000)

        history.record(song, artistSlug: "artist", artistName: "Artist", eraName: "Era", eraArt: nil, at: first)
        history.record(song, artistSlug: "artist", artistName: "Artist", eraName: "Era", eraArt: nil, at: second)

        let tally = history.entries(for: "artist").values.first
        #expect(tally?.count == 2)
        #expect(tally?.last == second)
        #expect(history.isHeard(song, artistSlug: "artist", eraName: "Era"))
        #expect(!history.isHeard(song, artistSlug: "other", eraName: "Era"))
    }

    @Test func `two placeholder versions with different files stay apart`() {
        let (history, _) = makeHistory()
        let first = version("???", link: "https://example.test/a")
        let second = version("???", link: "https://example.test/b")

        history.record(first, artistSlug: "artist", artistName: "Artist", eraName: "Era", eraArt: nil)

        #expect(history.isHeard(first, artistSlug: "artist", eraName: "Era"))
        #expect(!history.isHeard(second, artistSlug: "artist", eraName: "Era"))
    }

    @Test func `recording while disabled does nothing`() {
        let (history, _) = makeHistory(enabled: false)
        let song = version("Hurricane")

        history.record(song, artistSlug: "artist", artistName: "Artist", eraName: "Era", eraArt: nil)

        #expect(!history.isHeard(song, artistSlug: "artist", eraName: "Era"))
        #expect(history.recent.isEmpty)
    }

    @Test func `clear removes plays and recent`() {
        let (history, _) = makeHistory()
        history.record(version("Hurricane"), artistSlug: "artist", artistName: "Artist", eraName: "Era", eraArt: nil)

        history.clear()

        #expect(history.recent.isEmpty)
        #expect(history.entries(for: "artist").isEmpty)
    }

    @Test func `recent keeps the newest 30 distinct versions`() {
        let (history, _) = makeHistory()
        for index in 0..<35 {
            history.record(version("Song \(index)"), artistSlug: "artist", artistName: "Artist", eraName: "Era", eraArt: nil)
        }

        #expect(history.recent.count == 30)
        #expect(history.recent.first?.version.name == "Song 34")
        #expect(history.recent.last?.version.name == "Song 5")
    }

    @Test func `save and load round trip`() async {
        let (history, file) = makeHistory()
        let song = version("Hurricane", tag: "V4")
        history.record(song, artistSlug: "artist", artistName: "Artist", eraName: "Era", eraArt: "art.jpg")
        await history.flush()

        let reloaded = ListeningHistory(
            fileURL: file,
            defaults: UserDefaults(suiteName: "listening-\(UUID().uuidString)")!
        )

        #expect(reloaded.isHeard(song, artistSlug: "artist", eraName: "Era"))
        #expect(reloaded.recent.first?.artistName == "Artist")
        #expect(reloaded.recent.first?.eraArt == "art.jpg")
    }
}
