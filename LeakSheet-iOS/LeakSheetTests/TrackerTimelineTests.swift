import Foundation
import Testing

@testable import LeakSheet

@MainActor
struct TrackerTimelineTests {
    @Test func `an event repeated by the next era is listed once, and an era left empty drops out`() throws {
        let json: [String: Any] = ["eras": [
            ["name": "A", "timeline": [["date": "2010", "event": "Born"], ["date": "2012", "event": "A releases"]]],
            ["name": "B", "timeline": [["date": "2012", "event": "A releases"]]],
            [
                "name": "C",
                "timeline": [["date": "2012", "event": "A releases"], ["date": "2014", "event": "C releases"]]
            ]
        ]]
        struct Eras: Decodable { let eras: [Era] }
        let eras = try JSONDecoder().decode(Eras.self, from: JSONSerialization.data(withJSONObject: json)).eras
        let sections = TrackerTimelineSheet.sections(eras)
        #expect(sections.map(\.era.name) == ["A", "C"])
        #expect(sections.map { $0.events.map(\.event) } == [["Born", "A releases"], ["C releases"]])
    }

    @Test func `unknown dates are hidden`() {
        #expect(!EraTimelineList.hasDate("???"))
        #expect(!EraTimelineList.hasDate(" "))
        #expect(EraTimelineList.hasDate("Mid 2011"))
    }
}
