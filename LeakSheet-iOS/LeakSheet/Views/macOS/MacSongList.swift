#if os(macOS)
import SwiftUI

/// A row the Mac song list can show. Headers are non-selectable; only `.song` and
/// `.version` carry an id. Top-level because the list is generic over its header.
enum MacListRow: Identifiable {
    case header(String, id: String)
    /// An era's cover, name and song count above its songs in a list spanning eras.
    case eraHeader(Era, songCount: Int)
    case song(Song, version: SongVersion?, eraName: String, eraArt: String?, ordinal: Int)
    case version(SongVersion, song: Song, eraName: String, eraArt: String?, index: Int, ordinal: Int)

    var id: String {
        switch self {
        case .header(_, let id): "h:\(id)"
        case .eraHeader(let era, _): "e:\(era.name)"
        // Version id included: two versions of one song can both match a search
        // (as in FilterPipeline.SearchResult.id).
        case .song(let song, let version, let era, _, let ordinal):
            "s:\(era)::\(ordinal)::\(song.baseName)::\(version?.id ?? "")"
        case .version(let version, _, let era, _, let idx, let ordinal): "v:\(era)::\(ordinal)::\(idx)::\(version.id)"
        }
    }
}

/// One flat, selectable list of song/version rows. Click and Up/Down select, Return plays
/// the selection, double-click the row under the pointer, and the selection drives the
/// Details inspector.
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
    /// Page chrome, rendered as the first row so it scrolls away.
    @ViewBuilder var header: Header

    /// Owned here, not bound from the host: as a `@Binding` to the artist screen's
    /// `@State`, every arrow key rebuilt the host's whole row array.
    @State private var selected = MacListSelection()
    @FocusState private var listFocused: Bool

    private var selection: MacListRow.ID? { selected.id }

    private func select(_ id: MacListRow.ID?) {
        guard id != selected.id else { return }
        selected.id = id
        onSelect(id.flatMap { id in rows.first { $0.id == id } })
    }

    var body: some View {
        // No `List(selection:)`: see DECISIONS.md::MacSongList.swift::own-selection.
        ScrollViewReader { proxy in
            List {
                header
                    .listRowInsets(EdgeInsets())
                    .listRowSeparator(.hidden)
                    .selectionDisabled()

                ForEach(rows) { row in
                    rowView(row)
                        // Own the selection fill rather than letting the table paint a saturated accent
                        // slab over era-tinted panels.
                        .listRowBackground(MacSelectionFill(selected: selected, id: row.id))
                        .modifier(MacSelectedTrait(selected: selected, id: row.id))
                }
            }
            .listStyle(.inset)
            .scrollContentBackground(.hidden)
            .focusable()
            .focused($listFocused)
            .focusEffectDisabled()
            .onKeyPress(.upArrow) { moveSelection(by: -1, proxy) }
            .onKeyPress(.downArrow) { moveSelection(by: 1, proxy) }
            .onKeyPress(.return) { playSelection() ? .handled : .ignored }
            .onKeyPress(.rightArrow) { setSelectionExpanded(true) }
            .onKeyPress(.leftArrow) { setSelectionExpanded(false) }
            // Space is safe here (see DECISIONS.md::LeakSheetCommands.swift::arrow-modifiers):
            // `onKeyPress` fires only while the list has focus.
            .onKeyPress(.space) {
                guard PlayerViewModel.shared.currentTrack != nil else {
                    return playSelection() ? .handled : .ignored
                }
                PlayerViewModel.shared.togglePlay()
                return .handled
            }
        }
    }

    /// Up/Down step over headers to the next song or version row.
    private func moveSelection(by step: Int, _ proxy: ScrollViewProxy) -> KeyPress.Result {
        var index = rows.firstIndex { $0.id == selected.id } ?? (step > 0 ? -1 : rows.count)
        repeat { index += step } while rows.indices.contains(index) && !rows[index].isSelectable
        guard rows.indices.contains(index) else { return .handled }
        select(rows[index].id)
        proxy.scrollTo(rows[index].id)
        return .handled
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

        case .eraHeader(let era, let songCount):
            MacEraHeaderRow(era: era, songCount: songCount)
                .listRowSeparator(.hidden)
                .selectionDisabled()

        case .song(let song, let version, let eraName, let eraArt, let ordinal):
            MacSongRow(
                song: song, version: version,
                artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                eraName: eraName, eraArt: eraArt,
                onPlay: { onPlay($0, eraName) },
                onShowDescription: onShowDescription
            )
            // A multi-version song opens on ONE click: its versions are the point of the
            // row. The tap gesture takes the click from the List, so it sets the selection.
            .onTapGesture {
                select(row.id)
                listFocused = true
                if Self.isDoubleClick {
                    // On a multi-version row the first click already expanded it.
                    if let picked = version, picked.isStreamable { onPlay(picked, eraName) }
                    return
                }
                guard song.hasMultipleVersions, let onToggleExpansion else { return }
                onToggleExpansion(eraName, ordinal)
            }

        case .version(let version, let song, let eraName, let eraArt, _, _):
            MacSongRow(
                song: song, version: version,
                artistName: artistName, artistSlug: artistSlug, sourceUrl: sourceUrl,
                eraName: eraName, eraArt: eraArt,
                showVersionBadge: true, indented: true,
                onPlay: { onPlay($0, eraName) },
                onShowDescription: onShowDescription
            )
            .onTapGesture {
                select(row.id)
                listFocused = true
                if Self.isDoubleClick, version.isStreamable { onPlay(version, eraName) }
            }
        }
    }

    /// Read from the event: a second `count: 2` gesture delays every single click by the
    /// double-click interval while it waits.
    private static var isDoubleClick: Bool {
        // clickCount raises on non-mouse events, e.g. a VoiceOver press after arrowing.
        guard let event = NSApp.currentEvent, [.leftMouseDown, .leftMouseUp].contains(event.type) else { return false }
        return event.clickCount == 2
    }

    /// → expands the selected multi-version song; ← collapses it, also from one of its
    /// versions, and moves the selection up to the song.
    private func setSelectionExpanded(_ expand: Bool) -> KeyPress.Result {
        guard let onToggleExpansion, let selection,
              let index = rows.firstIndex(where: { $0.id == selection }) else { return .ignored }
        switch rows[index] {
        case .song(let song, _, let eraName, _, let ordinal) where song.hasMultipleVersions:
            var expanded = false
            if index + 1 < rows.count, case .version(_, _, let versionEra, _, _, let versionOrdinal) = rows[index + 1] {
                expanded = versionEra == eraName && versionOrdinal == ordinal
            }
            guard expand != expanded else { return .ignored }
            onToggleExpansion(eraName, ordinal)
            return .handled
        case .version(_, _, let eraName, _, _, let ordinal) where !expand:
            if let parent = rows[..<index].lastIndex(where: { if case .song = $0 { true } else { false } }) {
                select(rows[parent].id)
            }
            onToggleExpansion(eraName, ordinal)
            return .handled
        default:
            return .ignored
        }
    }

    /// Play whatever the selection points at. Returns false when the selection
    /// is a header, is missing, or has no streamable version.
    @discardableResult
    private func playSelection() -> Bool {
        guard let selection, let row = rows.first(where: { $0.id == selection }) else { return false }
        switch row {
        case .header, .eraHeader:
            return false
        case .song(let song, let version, let eraName, _, _):
            guard let picked = version ?? song.bestPlayableVersion, picked.isStreamable else { return false }
            onPlay(picked, eraName)
            return true
        case .version(let version, _, let eraName, _, _, _):
            guard version.isStreamable else { return false }
            onPlay(version, eraName)
            return true
        }
    }
}

/// A reference, so a selection change invalidates only the rows that read it.
@Observable
final class MacListSelection {
    var id: MacListRow.ID?
}

private struct MacSelectionFill: View {
    let selected: MacListSelection
    let id: MacListRow.ID
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        if selected.id == id {
            RoundedRectangle(cornerRadius: 6)
                .fill(Color.lsSelection(colorScheme))
                .padding(.horizontal, 6)
        }
    }
}

/// VoiceOver's "selected", read outside the list body like the fill.
private struct MacSelectedTrait: ViewModifier {
    let selected: MacListSelection
    let id: MacListRow.ID

    func body(content: Content) -> some View {
        content.accessibilityAddTraits(selected.id == id ? .isSelected : [])
    }
}

/// Cover, name and song count: the list's counterpart of the iOS era card.
private struct MacEraHeaderRow: View {
    let era: Era
    let songCount: Int

    var body: some View {
        HStack(spacing: 12) {
            Group {
                if let art = era.artUrl, let url = APIClient.shared.imageProxyURL(for: art, width: 480) {
                    MacEraCover(url: url, cacheKey: art, onColorExtracted: { _ in })
                } else {
                    ArtworkPlaceholder(cornerRadius: 0)
                }
            }
            .frame(width: 44, height: 44)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 2) {
                Text(era.name)
                    .font(.title3.weight(.semibold))
                    .lineLimit(1)
                Text("\(songCount) song\(songCount == 1 ? "" : "s")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.top, 14)
        .padding(.bottom, 4)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

extension MacListRow {
    var isSelectable: Bool {
        switch self {
        case .header, .eraHeader: false
        case .song, .version: true
        }
    }

    /// The detail payload this row describes, for the Details inspector.
    func payload(artistName: String, artistSlug: String) -> SongDetailPayload? {
        switch self {
        case .header, .eraHeader:
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
