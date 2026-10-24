import AppIntents
import CoreSpotlight

/// A favourited song. Plays from the saved snapshot, so it needs no network and no open tracker.
nonisolated struct FavouriteSongEntity: AppEntity, IndexedEntity {
    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "Favourite Song")
    static let defaultQuery = FavouriteSongQuery()

    let id: String
    let title: String
    let artist: String

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(title)", subtitle: "\(artist)")
    }

    var attributeSet: CSSearchableItemAttributeSet {
        let set = defaultAttributeSet
        set.artist = artist
        set.contentDescription = "Favourite leak by \(artist)"
        return set
    }

    init(id: String, title: String, artist: String) {
        self.id = id
        self.title = title
        self.artist = artist
    }

    init(entry: FavouritesManager.FavouriteEntry) {
        self.init(id: entry.key, title: entry.songBaseName, artist: entry.artistName)
    }
}

nonisolated struct FavouriteSongQuery: EntityStringQuery {
    @MainActor
    private func all() -> [FavouriteSongEntity] {
        FavouritesManager.shared.entries.map(FavouriteSongEntity.init(entry:))
    }

    func entities(for identifiers: [String]) async throws -> [FavouriteSongEntity] {
        await all().filter { identifiers.contains($0.id) }
    }

    func entities(matching string: String) async throws -> [FavouriteSongEntity] {
        let wanted = LibraryMatcher.normalize(string)
        return await all().filter {
            LibraryMatcher.normalize($0.title).contains(wanted) || LibraryMatcher.normalize($0.artist).contains(wanted)
        }
    }

    func suggestedEntities() async throws -> [FavouriteSongEntity] {
        await Array(all().prefix(10))
    }
}
