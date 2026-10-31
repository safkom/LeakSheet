import Foundation
import Testing

@testable import LeakSheet

@MainActor
struct EraInsightsTests {
    private func version(_ name: String, leak: String? = nil, file: String? = nil, quality: String? = nil,
                         producers: String? = nil, featuring: String? = nil, link: String? = nil) -> [String: Any] {
        var v: [String: Any] = ["name": name]
        if let leak { v["leak_date"] = leak }
        if let file { v["file_date"] = file }
        if let quality { v["quality"] = quality }
        if let producers { v["producers"] = producers }
        if let featuring { v["featuring"] = featuring }
        if let link { v["links"] = [link] }
        return v
    }

    private func artist() throws -> Artist {
        let songs: [[String: Any]] = [
            ["base_name": "One", "versions": [
                version("One [V1]", leak: "01/02/2020", quality: "CD Quality", producers: "Maker, Other",
                        link: "https://pillows.su/f/aaa"),
                version("One [V2]", leak: "not a date", quality: "Lossless", producers: "maker", featuring: "Guest")
            ]],
            ["base_name": "Two", "versions": [
                version(
                    "Two",
                    leak: "03/04/2019",
                    file: "05/06/2018",
                    quality: "CD Quality",
                    producers: "Maker & Third"
                )
            ]]
        ]
        let json: [String: Any] = [
            "name": "Artist", "slug": "artist",
            "eras": [
                ["name": "First", "sections": [["name": "Main", "songs": songs]]],
                ["name": "Second", "sections": []],
                ["name": "Third", "sections": []]
            ],
            "tabs": [["kind": "misc", "name": "Misc", "entries": [
                ["era_name": "first", "name": "Interview", "links": [], "source_tab": "misc"],
                ["era_name": "Second", "name": "Other", "links": [], "source_tab": "misc"]
            ]]]
        ]
        return try JSONDecoder().decode(Artist.self, from: JSONSerialization.data(withJSONObject: json))
    }

    @Test func `counts, quality tiers and top credits`() throws {
        let a = try artist()
        let insights = EraInsights.compute(era: a.eras[0], artist: a)
        #expect(insights.versionCount == 3)
        #expect(insights.playableCount == 1)
        #expect(insights.quality.map(\.variant) == [.lossless, .cd])
        #expect(insights.quality.map(\.count) == [1, 2])
        // Case-folded: "Maker" and "maker" are one producer, counted three times.
        #expect(insights.topProducers.first == .init(label: "Maker", value: 3))
        #expect(insights.topFeatures.map(\.label) == ["Guest"])
        #expect(insights.sections == [.init(label: "Main", value: 2)])
    }

    @Test func `the tracker's own artist never counts as a feature`() throws {
        let versions = ["Star", "Star", "Star", "Guest", "Star & Guest", "Sheet Name"].enumerated().map {
            version("Song \($0.offset)", featuring: $0.element)
        }
        let json: [String: Any] = [
            "name": "Sheet Name", "slug": "s",
            "eras": [[
                "name": "Only",
                "sections": [["name": "", "songs": [["base_name": "Song", "versions": versions]]]]
            ]]
        ]
        let a = try JSONDecoder().decode(Artist.self, from: JSONSerialization.data(withJSONObject: json))
        // "Star" leads "Guest" 4 to 2, so it is the sheet's artist; the sheet name is dropped too.
        #expect(EraInsights.compute(era: a.eras[0], artist: a).topFeatures.map(\.label) == ["Guest"])
    }

    @Test func `date ranges skip strings that do not parse`() throws {
        let a = try artist()
        let insights = EraInsights.compute(era: a.eras[0], artist: a)
        #expect(insights.leakDates == .init(first: "03/04/2019", last: "01/02/2020"))
        #expect(insights.fileDates == .init(first: "05/06/2018", last: "05/06/2018"))
        #expect(EraInsights.dateRange(["nope"]) == nil)
    }

    @Test func `file dates fall back to the recording date`() throws {
        let json: [String: Any] = [
            "name": "A", "slug": "a",
            "eras": [["name": "E", "sections": [["name": "", "songs": [["base_name": "S", "versions": [
                ["name": "S", "date_of_recording": "02/03/2019"], ["name": "S [V2]", "file_date": "01/01/2018"]
            ]]]]]]]
        ]
        let a = try JSONDecoder().decode(Artist.self, from: JSONSerialization.data(withJSONObject: json))
        #expect(EraInsights.compute(era: a.eras[0], artist: a).fileDates == .init(
            first: "01/01/2018",
            last: "02/03/2019"
        ))
    }

    @Test func `misc entries match the era by key, and neighbours stop at the ends`() throws {
        let a = try artist()
        let first = EraInsights.compute(era: a.eras[0], artist: a)
        #expect(first.miscEntries.map(\.name) == ["Interview"])
        #expect(first.previousEra == nil)
        #expect(first.nextEra == "Second")
        let last = EraInsights.compute(era: a.eras[2], artist: a)
        #expect(last.previousEra == "Second")
        #expect(last.nextEra == nil)
    }
}
