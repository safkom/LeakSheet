import Foundation

/// Everything a song-detail screen needs to render one version in context.
///
/// Lives in Shared rather than nested in the iOS detail sheet because it is
/// pure model data that `FavouritesManager` builds and every platform's detail
/// screen consumes. `SongDescriptionSheet.Payload` remains a typealias for it,
/// so the iOS call sites are unchanged.
/// Hashable so tvOS can push one as a `NavigationStack` path value; `Song` and
/// `SongVersion` are already Hashable, so the conformance is synthesized.
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
