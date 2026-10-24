import Foundation
#if !os(tvOS)
import MusicKit
#endif

/// Finds the Apple Music page of a released song, for versions the tracker marks as on streaming.
/// The tracker has no ISRC, so the match is exact normalized title plus artist.
nonisolated enum AppleMusicMatch {
    static func isMatch(artist: String, title: String, songArtist: String, songTitle: String) -> Bool {
        let want = LibraryMatcher.normalize(LyricsParsing.searchTitle(title))
        guard !want.isEmpty, LibraryMatcher.normalize(LyricsParsing.searchTitle(songTitle)) == want else { return false }
        return LibraryMatcher.candidates(songArtist).contains(LibraryMatcher.normalize(artist))
    }
}

actor AppleMusicCatalog {
    static let shared = AppleMusicCatalog()
    private var cache: [String: URL?] = [:]

    /// The catalog page for an exact match, nil when none or when the lookup fails (not cached).
    func songURL(artist: String, title: String) async -> URL? {
        #if os(tvOS)
        return nil
        #else
        let key = LibraryMatcher.normalize(artist) + "|" + LibraryMatcher.normalize(title)
        if let cached = cache[key] { return cached }
        var request = MusicCatalogSearchRequest(term: "\(artist) \(LyricsParsing.searchTitle(title))", types: [MusicKit.Song.self])
        request.limit = 10
        guard let songs = try? await request.response().songs else { return nil }
        let url = songs.first {
            AppleMusicMatch.isMatch(artist: artist, title: title, songArtist: $0.artistName, songTitle: $0.title)
        }?.url
        cache[key] = url
        return url
        #endif
    }
}
