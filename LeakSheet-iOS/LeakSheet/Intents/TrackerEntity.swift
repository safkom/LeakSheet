import AppIntents
import CoreSpotlight

/// A tracker Siri, Shortcuts and Spotlight can name. The id is the tracker URL, which is what the loader takes.
nonisolated struct TrackerEntity: AppEntity, IndexedEntity {
    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "Tracker")
    static let defaultQuery = TrackerQuery()

    let id: String
    let name: String

    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(name)") }

    var attributeSet: CSSearchableItemAttributeSet {
        let set = defaultAttributeSet
        set.contentDescription = "Unreleased music tracker"
        set.keywords = ["tracker", "leaks", "unreleased"]
        return set
    }
}

/// Recent trackers first, then the ArtistGrid list, one entry per name.
enum TrackerCatalog {
    @MainActor
    static func recents() -> [TrackerEntity] {
        RecentTrackersManager.shared.trackers.map { TrackerEntity(id: $0.sourceUrl, name: $0.name) }
    }

    static func all() async -> [TrackerEntity] {
        let listed = (try? await APIClient.shared.fetchTrackers()) ?? []
        let merged = await recents() + listed.map { TrackerEntity(id: $0.url, name: $0.name) }
        var seen = Set<String>()
        return merged.filter { seen.insert(LibraryMatcher.normalize($0.name)).inserted }
    }
}

nonisolated struct TrackerQuery: EntityStringQuery {
    func entities(for identifiers: [String]) async throws -> [TrackerEntity] {
        await TrackerCatalog.all().filter { identifiers.contains($0.id) }
    }

    func entities(matching string: String) async throws -> [TrackerEntity] {
        let wanted = LibraryMatcher.normalize(string)
        return await TrackerCatalog.all().filter { LibraryMatcher.normalize($0.name).contains(wanted) }
    }

    func suggestedEntities() async throws -> [TrackerEntity] {
        await TrackerCatalog.recents()
    }
}
