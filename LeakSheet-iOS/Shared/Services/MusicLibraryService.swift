import Foundation
#if !os(tvOS)
import MusicKit
#endif

/// Reads the user's Apple Music library for tracker recommendations. Stays on device:
/// library names are matched locally and never sent to the backend.
enum MusicLibraryService {
    enum Access { case unknown, granted, denied }

    static var access: Access {
        #if os(tvOS)
        .denied
        #else
        switch MusicAuthorization.currentStatus {
        case .authorized: .granted
        case .notDetermined: .unknown
        default: .denied
        }
        #endif
    }

    /// Prompts on first use, so call it from a user action. Returns false when denied.
    static func requestAccess() async -> Bool {
        #if os(tvOS)
        false
        #else
        await MusicAuthorization.request() == .authorized
        #endif
    }

    /// One read per process: every Explore open asked for the whole library again, and
    /// opens that overlapped each held a full copy of it.
    private static var libraryRead: Task<[LibraryArtist], Never>?

    /// Artists from the library's songs, with summed play counts. Empty when access is missing.
    static func libraryArtists(
        load: @escaping @Sendable () async -> [LibraryArtist] = readLibrary
    ) async -> [LibraryArtist] {
        if let libraryRead { return await libraryRead.value }
        let read = Task { await load() }
        libraryRead = read
        let artists = await read.value
        // Empty also means "no access yet": the next call must ask again.
        if artists.isEmpty, libraryRead == read { libraryRead = nil }
        return artists
    }

    /// Pull-to-refresh: the next call reads the library again.
    static func forgetLibrary() { libraryRead = nil }

    /// Off the main actor: a large library is tens of thousands of songs to walk.
    @concurrent
    private nonisolated static func readLibrary() async -> [LibraryArtist] {
        #if os(tvOS)
        []
        #else
        guard MusicAuthorization.currentStatus == .authorized else { return [] }
        guard let songs = try? await MusicLibraryRequest<MusicKit.Song>().response().items else { return [] }
        var plays: [String: Int] = [:]
        for song in songs { plays[song.artistName, default: 0] += song.playCount ?? 0 }
        return plays.map { LibraryArtist(name: $0.key, plays: $0.value) }
        #endif
    }
}
