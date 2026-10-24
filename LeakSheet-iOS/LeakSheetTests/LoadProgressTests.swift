import Foundation
import Testing

@testable import LeakSheet

struct LoadProgressTests {
    @Test func unitsNeverMoveBackwardsAcrossPhases() {
        let phases: [APIClient.LoadPhase] = [
            .readingCache, .connecting,
            .server(message: "Reading tabs", done: nil, total: nil),
            .server(message: "Reading tabs", done: 3, total: 6),
            .downloading(receivedBytes: 0, expectedBytes: nil),
            .downloading(receivedBytes: 50, expectedBytes: 100),
            .preparing,
        ]
        let units = phases.map { LoadProgress.of($0).units }
        #expect(units == units.sorted())
        #expect(units.allSatisfy { (0...100).contains($0) })
    }

    @Test func overshootingCountsStayInRange() {
        #expect(LoadProgress.of(.server(message: "x", done: 9, total: 3)).units == 60)
        #expect(LoadProgress.of(.downloading(receivedBytes: 500, expectedBytes: 100)).units == 90)
    }
}
