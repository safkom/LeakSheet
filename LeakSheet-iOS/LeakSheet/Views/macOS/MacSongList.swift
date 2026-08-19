#if os(macOS)
import SwiftUI

/// One flat, selectable list of song/version rows.
///
/// `List(selection:)` is what buys the Mac behaviours for free: click to select,
/// ↑↓ to move, shift-click to extend, and a focus ring. Return plays the
/// selection; double-click plays the row under the pointer. Details is no longer
/// bound to a click at all — the selection drives the inspector.
struct MacSongList: View {
    /// A row the list can show. Headers are non-selectable; only `.song` and
    /// `.version` carry an id the selection can land on.
    enum Row: Identifiable {
        case header(String, id: String)
        case song(Song, version: SongVersion?, eraName: String, eraArt: String?, ordinal: Int)
        case version(SongVersion, song: Song, eraName: String, eraArt: String?, index: Int, ordinal: Int)

        var id: String {
            switch self {
            case .header(_, let id): "h:\(id)"
            // Version id included: two versions of one song can both match a
            // search, and era+ordinal+name alone would collide (the same
            // reason FilterPipeline.SearchResult.id carries it).
            case .song(let s, let v, let era, _, let ordinal): "s:\(era)::\(ordinal)::\(s.baseName)::\(v?.id ?? "")"
            case .version(let v, _, let era, _, let idx, let ordinal): "v:\(era)::\(ordinal)::\(idx)::\(v.id)"
            }
        }

        var isSelectable: Bool {
            if case .header = self { return false }
            return true
        }
    }

    let rows: [Row]
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    /// Expand/collapse a multi-version song. Nil in flat contexts (search,
    /// recents, favourites) where versions are already listed individually.
    var onToggleExpansion: ((String, Int) -> Void)?
    let onPlay: (SongVersion, String) -> Void
    let onShowDescription: (DescriptionSheet.Payload) -> Void

    @Binding var selection: Row.ID?

    var body: some View {
        List(rows, selection: $selection) { row in
            switch row {
            case .header(let text, _):
                Text(text)
                    .font(.caption.weight(.bold))
                    .textCase(.uppercase)
                    .foregroundStyle(.secondary)
                    .padding(.top, 10)
                    .selectionDisabled()

            case .song(let song, let version, let eraName, let eraArt, let ordinal):
                MacSongRow(
                    song: song, version: version,
                    artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                    eraName: eraName, eraArt: eraArt,
                    onPlay: { onPlay($0, eraName) },
                    onShowDescription: onShowDescription
                )
                // Double-click plays; a multi-version song expands instead,
                // because "play" for a song with eight versions is a guess.
                .onTapGesture(count: 2) {
                    if song.hasMultipleVersions, let onToggleExpansion {
                        onToggleExpansion(eraName, ordinal)
                    } else if let v = version, v.isStreamable {
                        onPlay(v, eraName)
                    }
                }

            case .version(let version, let song, let eraName, let eraArt, let index, _):
                MacSongRow(
                    song: song, version: version,
                    artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                    eraName: eraName, eraArt: eraArt,
                    showVersionBadge: true, indented: true,
                    onPlay: { onPlay($0, eraName) },
                    onShowDescription: onShowDescription
                )
                .id(index)
                .onTapGesture(count: 2) {
                    if version.isStreamable { onPlay(version, eraName) }
                }
            }
        }
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .onKeyPress(.return) { playSelection() ? .handled : .ignored }
        // Space is safe here and not in the menu bar: `onKeyPress` fires only
        // while the list itself has focus, so it can't steal the key from the
        // tracker URL field the way a menu key equivalent would.
        .onKeyPress(.space) {
            guard PlayerViewModel.shared.currentTrack != nil else {
                return playSelection() ? .handled : .ignored
            }
            PlayerViewModel.shared.togglePlay()
            return .handled
        }
    }

    /// Play whatever the selection points at. Returns false when the selection
    /// is a header, is missing, or has no streamable version.
    @discardableResult
    private func playSelection() -> Bool {
        guard let selection, let row = rows.first(where: { $0.id == selection }) else { return false }
        switch row {
        case .header:
            return false
        case .song(let song, let version, let eraName, _, _):
            guard let v = version ?? song.bestPlayableVersion, v.isStreamable else { return false }
            onPlay(v, eraName)
            return true
        case .version(let version, _, let eraName, _, _, _):
            guard version.isStreamable else { return false }
            onPlay(version, eraName)
            return true
        }
    }
}

extension MacSongList.Row {
    /// The detail payload this row describes, for the Details inspector.
    func payload(artistName: String, artistSlug: String) -> SongDetailPayload? {
        switch self {
        case .header:
            nil
        case .song(let song, let version, let eraName, let eraArt, _):
            (version ?? song.bestPlayableVersion ?? song.versions.first).map {
                SongDetailPayload(
                    song: song, version: $0,
                    artistName: artistName, artistSlug: artistSlug,
                    eraName: eraName, eraArt: eraArt
                )
            }
        case .version(let version, let song, let eraName, let eraArt, _, _):
            SongDetailPayload(
                song: song, version: version,
                artistName: artistName, artistSlug: artistSlug,
                eraName: eraName, eraArt: eraArt
            )
        }
    }
}
#endif
