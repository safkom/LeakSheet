#if os(macOS)
import SwiftUI

/// A row the Mac song list can show. Headers are non-selectable; only `.song`
/// and `.version` carry an id the selection can land on.
///
/// Top-level rather than nested in `MacSongList`: the list is generic over its
/// header view, and `MacSongList.Row` would need the generic argument spelled
/// out at every use site.
enum MacListRow: Identifiable {
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

/// One flat, selectable list of song/version rows.
///
/// `List(selection:)` is what buys the Mac behaviours for free: click to select,
/// ↑↓ to move, shift-click to extend, and a focus ring. Return plays the
/// selection; double-click plays the row under the pointer. Details is no longer
/// bound to a click at all — the selection drives the inspector.
struct MacSongList<Header: View>: View {
    let rows: [MacListRow]
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    /// Expand/collapse a multi-version song. Nil in flat contexts (search,
    /// recents, favourites) where versions are already listed individually.
    var onToggleExpansion: ((String, Int) -> Void)?
    let onPlay: (SongVersion, String) -> Void
    let onShowDescription: (DescriptionSheet.Payload) -> Void
    /// Reports the newly selected row so the host can drive the Details panel.
    let onSelect: (MacListRow?) -> Void
    /// Page chrome, rendered as the first row so it scrolls away. Pinned above
    /// the list it cost ~290pt of a 700pt window — a quarter of the screen
    /// spent on context you read once.
    @ViewBuilder var header: Header

    /// Owned here, not bound from the host.
    ///
    /// As `@Binding` to the artist screen's `@State`, every arrow-key press
    /// invalidated that whole view — which recomputed the row array from
    /// scratch. On a badge-filtered Ye that is ~6000 rows rebuilt per keypress.
    /// Selection is this list's business; the host only needs the result.
    @State private var selection: MacListRow.ID?
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        List(selection: $selection) {
            header
                .listRowInsets(EdgeInsets())
                .listRowSeparator(.hidden)
                .selectionDisabled()

            ForEach(rows) { row in
                rowView(row)
                    // Own the selection fill rather than letting the table paint
                    // a saturated accent slab over an app whose panels are all
                    // era-tinted.
                    .listRowBackground(
                        row.id == selection
                            ? RoundedRectangle(cornerRadius: 6)
                                .fill(Color.lsSelection(colorScheme))
                                .padding(.horizontal, 6)
                            : nil
                    )
            }
        }
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .onChange(of: selection) { _, id in
            onSelect(id.flatMap { id in rows.first { $0.id == id } })
        }
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

    @ViewBuilder
    private func rowView(_ row: MacListRow) -> some View {
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
            // A multi-version song opens on ONE click — the versions are the
            // point of the row, and hiding them behind a double-click made
            // every such song a two-step. Selection is set here too because
            // the tap gesture takes the click from the List.
            .onTapGesture(count: 1) {
                // Selection is set FIRST and unconditionally: this gesture takes
                // the click from the List for every song row, so leaving it
                // behind the multi-version guard meant a single-version song
                // could never be selected by clicking it and the Details
                // inspector never followed.
                selection = row.id
                guard song.hasMultipleVersions, let onToggleExpansion else { return }
                onToggleExpansion(eraName, ordinal)
            }
            // Double-click plays. On a multi-version row the first click
            // already expanded, so this only fires for single-version songs —
            // where "play" is unambiguous.
            .onTapGesture(count: 2) {
                if let v = version, v.isStreamable { onPlay(v, eraName) }
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

extension MacListRow {
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
