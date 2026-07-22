import Foundation
import Testing

@testable import LeakSheet

// MARK: - Fixtures

private func version(_ name: String, tag: String? = nil, notes: String? = nil) -> SongVersion {
    SongVersion(
        name: name, versionTag: tag, badge: nil, featuring: nil, producers: nil,
        collaboration: nil, refs: nil, creditedArtists: nil, altTitles: nil, notes: notes, ogFilename: nil,
        ogFilenames: nil, samples: nil, trackLength: nil, fileDate: nil, leakDate: nil,
        availableLength: nil, quality: nil, links: nil, qualityColor: nil,
        availableLengthColor: nil, dateOfRecording: nil, type: nil, sources: nil, rating: nil
    )
}

private func era(_ name: String, versions: [SongVersion], artist: String = "Ye") -> EraSongContext {
    EraSongContext(eraName: name, artistName: artist, artUrl: "art:\(name)", versions: versions, artistSlug: "ye")
}

private func listItem(_ v: SongVersion, era: String = "Donda") -> PlaybackListItem {
    PlaybackListItem(version: v, artistName: "Ye", eraName: era, artUrl: "", artistSlug: "ye")
}

private func playedName(_ advance: PlaybackQueueLogic.Advance) -> String? {
    if case .play(let t) = advance { return t.version.name }
    return nil
}

// MARK: - Tests

struct PlaybackQueueLogicTests {
    @Test func `era advance walks versions in order and stops after last era`() {
        var logic = PlaybackQueueLogic()
        let songs = [version("A"), version("B"), version("C")]
        let ctx = era("Yeezus", versions: songs)
        logic.setArtistEras([ctx])
        _ = logic.playInEra(songs[0], context: ctx)

        #expect(playedName(logic.next()) == "B")
        #expect(playedName(logic.next()) == "C")
        #expect(logic.next() == .stop)
    }

    @Test func `era advance rolls over into the next non-empty era`() {
        var logic = PlaybackQueueLogic()
        let first = era("Yeezus", versions: [version("A")])
        let empty = era("Cruel Winter", versions: [])
        let second = era("Donda", versions: [version("X"), version("Y")])
        logic.setArtistEras([first, empty, second])
        _ = logic.playInEra(first.versions[0], context: first)

        #expect(playedName(logic.next()) == "X")
        #expect(playedName(logic.next()) == "Y")
        #expect(logic.next() == .stop)
    }

    @Test func `duplicate name-tag pairs advance by position, not first match`() {
        // Two distinct '???' mystery tracks with the same (name, tag) but
        // different notes. Starting at the SECOND must advance to C — the
        // old identity search matched the first '???' and replayed B.
        var logic = PlaybackQueueLogic()
        let dup1 = version("???", tag: "V1", notes: "first mystery")
        let dup2 = version("???", tag: "V1", notes: "second mystery")
        let ctx = era("Donda", versions: [dup1, dup2, version("C")])
        _ = logic.playInEra(dup2, context: ctx)

        #expect(playedName(logic.next()) == "C")
    }

    @Test func `queue interlude does not lose the era position`() {
        var logic = PlaybackQueueLogic()
        let songs = [version("A"), version("B"), version("C")]
        let ctx = era("Yeezus", versions: songs)
        _ = logic.playInEra(songs[0], context: ctx)

        logic.addToQueue(version("Queued"), artistName: "Other", eraName: "", artUrl: "")
        #expect(playedName(logic.next()) == "Queued")   // queue wins
        #expect(playedName(logic.next()) == "B")        // era resumes at B, not next era
    }

    @Test func `queue always wins over list and era contexts`() {
        var logic = PlaybackQueueLogic()
        _ = logic.playInList([listItem(version("L1")), listItem(version("L2"))], startAt: 0)
        logic.addToQueue(version("Q"), artistName: "", eraName: "", artUrl: "")

        #expect(playedName(logic.next()) == "Q")
        #expect(playedName(logic.next()) == "L2")
    }

    @Test func `list advance stops at end without era rollover`() {
        var logic = PlaybackQueueLogic()
        logic.setArtistEras([era("Yeezus", versions: [version("A")])])
        _ = logic.playInList([listItem(version("L1")), listItem(version("L2"))], startAt: 1)

        #expect(logic.next() == .stop)
    }

    @Test func `previous restarts when more than three seconds in`() {
        var logic = PlaybackQueueLogic()
        let ctx = era("Yeezus", versions: [version("A"), version("B")])
        _ = logic.playInEra(ctx.versions[1], context: ctx)

        #expect(logic.previous(currentTime: 5) == .restart)
        #expect(playedName(logic.previous(currentTime: 1)) == "A")
        #expect(logic.previous(currentTime: 1) == .restart)  // at start of era
    }

    @Test func `previous steps back up an ad-hoc list`() {
        var logic = PlaybackQueueLogic()
        _ = logic.playInList([listItem(version("L1")), listItem(version("L2"))], startAt: 1)

        #expect(playedName(logic.previous(currentTime: 0)) == "L1")
        #expect(logic.previous(currentTime: 0) == .restart)
    }

    @Test func `queue mutations — add remove move clear and cap`() {
        var logic = PlaybackQueueLogic()
        for i in 0..<3 {
            logic.addToQueue(version("Q\(i)"), artistName: "", eraName: "", artUrl: "")
        }
        #expect(logic.queue.map(\.version.name) == ["Q0", "Q1", "Q2"])
        #expect(Set(logic.queue.map(\.id)).count == 3)  // unique ids

        logic.moveInQueue(from: IndexSet(integer: 2), to: 0)
        #expect(logic.queue.map(\.version.name) == ["Q2", "Q0", "Q1"])

        logic.removeFromQueue(at: 1)
        #expect(logic.queue.map(\.version.name) == ["Q2", "Q1"])

        logic.removeFromQueue(at: 99)  // out of bounds is a no-op
        #expect(logic.queue.count == 2)

        logic.clearQueue()
        #expect(logic.queue.isEmpty)
    }

    @Test func `playFromQueue dequeues the tapped item`() {
        var logic = PlaybackQueueLogic()
        logic.addToQueue(version("Q0"), artistName: "", eraName: "", artUrl: "")
        logic.addToQueue(version("Q1"), artistName: "", eraName: "", artUrl: "")

        let target = logic.playFromQueue(at: 1)
        #expect(target?.version.name == "Q1")
        #expect(logic.queue.map(\.version.name) == ["Q0"])
        #expect(logic.playFromQueue(at: 5) == nil)
    }

    @Test func `next with no contexts stops`() {
        var logic = PlaybackQueueLogic()
        #expect(logic.next() == .stop)
    }

    @Test func `setArtistEras after setEraSongs still rolls over via name match`() {
        var logic = PlaybackQueueLogic()
        let first = era("Yeezus", versions: [version("A")])
        let second = era("Donda", versions: [version("X")])
        _ = logic.playInEra(first.versions[0], context: first)
        logic.setArtistEras([first, second])  // ran late — positional hint lost

        #expect(playedName(logic.next()) == "X")
    }

    @Test func `duplicate era names disambiguate via recorded position`() {
        var logic = PlaybackQueueLogic()
        let bonusA = era("Bonus Tracks", versions: [version("A1"), version("A2")])
        let lp = era("The Album", versions: [version("T1")])
        let bonusB = era("Bonus Tracks", versions: [version("B1")], artist: "Ye")
        logic.setArtistEras([bonusA, lp, bonusB])
        // Start in the SECOND "Bonus Tracks" (matches artUrl/count of bonusB).
        _ = logic.playInEra(bonusB.versions[0], context: bonusB)

        #expect(logic.next() == .stop)  // nothing after bonusB — must NOT jump to lp
    }
}
