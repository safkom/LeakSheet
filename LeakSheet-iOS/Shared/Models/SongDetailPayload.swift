import Foundation

/// Everything a song-detail screen needs to render one version in context.
///
/// Hashable so tvOS can push one as a `NavigationStack` path value.
/// See DECISIONS.md::SongDetailPayload
struct SongDetailPayload: Identifiable, Hashable {
    let id = UUID()
    /// Nil when the payload came from a saved favourite rather than a live
    /// tracker row — there is no surrounding Song to show sibling versions from.
    let song: Song?
    let version: SongVersion
    let artistName: String
    let artistSlug: String?
    let eraName: String
    let eraArt: String?
}
