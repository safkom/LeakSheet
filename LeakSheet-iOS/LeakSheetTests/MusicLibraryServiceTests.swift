import Foundation
import Testing

@testable import LeakSheet

/// The library read is the expensive part of Explore: one read per process, shared by callers.
@MainActor
@Suite(.serialized)
struct MusicLibraryServiceTests {
    private actor Counter {
        var loads = 0
        func load(_ result: [LibraryArtist]) async -> [LibraryArtist] {
            loads += 1
            try? await Task.sleep(for: .milliseconds(20))
            return result
        }
    }

    private let artists = [LibraryArtist(name: "Artist", plays: 3)]

    @Test func `callers that overlap share one library read, and later ones reuse it`() async {
        MusicLibraryService.forgetLibrary()
        let counter = Counter()
        let artists = artists
        async let first = MusicLibraryService.libraryArtists { await counter.load(artists) }
        async let second = MusicLibraryService.libraryArtists { await counter.load(artists) }
        let results = await [first, second]
        let third = await MusicLibraryService.libraryArtists { await counter.load(artists) }
        #expect(results == [artists, artists])
        #expect(third == artists)
        #expect(await counter.loads == 1)
    }

    @Test func `an empty read is not kept, so granting access later still works`() async {
        MusicLibraryService.forgetLibrary()
        let counter = Counter()
        let artists = artists
        #expect(await MusicLibraryService.libraryArtists { await counter.load([]) }.isEmpty)
        #expect(await MusicLibraryService.libraryArtists { await counter.load(artists) } == artists)
        #expect(await counter.loads == 2)
    }
}
