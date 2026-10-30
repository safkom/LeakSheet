import SwiftUI

struct MiscListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    /// era name (lowercased) → art URL, precomputed once by the parent so
    /// this view doesn't need the artist's whole (potentially large) era tree.
    let eraArtByLowercasedName: [String: String?]
    let onShowDescription: (DescriptionSheet.Payload) -> Void
    /// Non-stream link taps route up to the parent, which owns the Safari
    /// and embed-player sheets.
    let onOpenLink: (MiscLink) -> Void

    @Environment(PlayerViewModel.self) private var player
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Expanded era groups — presentation-only, keyed on eraName. A live
    /// search expands everything so results are never hidden, and a page
    /// with a single group starts open.
    @State private var expandedEras: Set<String> = []

    private func isExpanded(_ eraName: String, groupCount: Int) -> Bool {
        vm.isSearching || groupCount <= 1 || expandedEras.contains(eraName)
    }

    /// The badge filter that can empty a content tab, named as the Filters menu labels it.
    static func emptyFilterName(_ vm: ArtistViewModel) -> String? {
        if vm.grails { return "Grails" }
        if vm.bestOf { return "Best Of" }
        if vm.worstOf { return "Worst Of" }
        return nil
    }

    /// Normalised key for `vm.eraDisplay`, used for reads and writes alike (the card
    /// shows "Other" for an empty name and matches art case-insensitively).
    private func colorKey(_ eraName: String) -> String {
        eraName.isEmpty ? "Other" : eraName
    }

    /// A minimal `Era` so a content-tab group renders through the same `EraCardView`
    /// as the main list; the card reads only name and art.
    private func eraForGroup(_ group: MiscEraGroup) -> Era {
        Era(
            name: group.eraName.isEmpty ? "Other" : group.eraName,
            altNames: nil,
            description: nil,
            timeline: nil,
            artUrl: eraArtByLowercasedName[group.eraName.lowercased()] ?? nil,
            sections: nil,
            songCount: nil,
            versionCount: nil
        )
    }

    var body: some View {
        let entries = vm.content.miscResults

        if entries.isEmpty {
            if vm.isFiltering {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 32)
            } else {
                // Name the page the user is on: this branch renders every content tab.
                ContentUnavailableView(
                    "No \(vm.selectedTabName ?? "Misc") Entries",
                    systemImage: "film.stack",
                    // Say which filter is responsible, not "the current filters".
                    description: Text(
                        vm.noSnippets ? "Hide Snippets is on. Turn it off in Filters to see snippet entries."
                        : !vm.content.state.query.isEmpty ? "Nothing on this page matches your search."
                        : Self.emptyFilterName(vm).map { "No \($0) on this page." } ?? "This page has no entries."
                    )
                )
                .padding(.top, 40)
            }
        } else {
            // Shared EraCardView — see DECISIONS.md::ArtistContentLists.swift::era-card-reuse
            // One flat row per card, section label and entry, each a direct LazyVStack
            // child, so an expanded group doesn't build every row at once.
            let groups = vm.content.miscEraGroups
            let playOrder = groups.flatMap(\.entries)
            ForEach(rows(for: groups)) { row in
                switch row {
                case .card(let group, let expanded):
                    EraCardView(
                        era: eraForGroup(group),
                        expanded: expanded,
                        displayColors: vm.eraDisplay[colorKey(group.eraName)],
                        subtitle: "\(group.entries.count.formatted()) entr\(group.entries.count == 1 ? "y" : "ies")",
                        onTap: {
                            withAnimation(reduceMotion ? nil : .spring(duration: 0.3, bounce: 0.1)) {
                                if expandedEras.contains(group.eraName) {
                                    expandedEras.remove(group.eraName)
                                } else {
                                    expandedEras.insert(group.eraName)
                                }
                            }
                        },
                        onColorExtracted: { color in
                            vm.setEraColor(eraName: colorKey(group.eraName), dominant: color)
                        }
                    )
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                case .section(let name, let eraName, _):
                    MiscSectionHeader(name: name, displayColors: vm.eraDisplay[colorKey(eraName)])
                case .entry(let entry, let eraName, let isLast):
                    MiscEntryRowView(
                        entry: entry,
                        artistName: artistName,
                        artistSlug: artistSlug,
                        eraArt: eraArtUrl(for: entry.eraName),
                        // Auto-advance follows the order on screen (grouped by era).
                        onPlay: { _ in playEntry(entry, in: playOrder) },
                        onShowDescription: onShowDescription,
                        onSelectLink: onOpenLink
                    )
                    .contentShape(Rectangle())
                    .accessibilityAddTraits(.isButton)
                    .onTapGesture { handleRowTap(entry) }
                    .songPanel(vm.eraDisplay[colorKey(eraName)], isLast: isLast)
                }
            }
        }
    }

    private enum MiscRow: Identifiable {
        case card(MiscEraGroup, expanded: Bool)
        case section(String, eraName: String, ordinal: Int)
        case entry(MiscEntry, eraName: String, isLast: Bool)

        var id: String {
            switch self {
            case .card(let group, _): "card::\(group.eraName)"
            case .section(let name, let era, let ordinal): "sec::\(era)::\(ordinal)::\(name)"
            case .entry(let entry, _, _): "entry::\(entry.id)"
            }
        }
    }

    private func rows(for groups: [MiscEraGroup]) -> [MiscRow] {
        var rows: [MiscRow] = []
        for group in groups {
            let expanded = isExpanded(group.eraName, groupCount: groups.count)
            rows.append(.card(group, expanded: expanded))
            guard expanded else { continue }
            var currentSection = ""
            for (i, entry) in group.entries.enumerated() {
                if let section = entry.section, !section.isEmpty, section != currentSection {
                    rows.append(.section(section, eraName: group.eraName, ordinal: rows.count))
                }
                currentSection = entry.section ?? ""
                rows.append(.entry(entry, eraName: group.eraName, isLast: i == group.entries.count - 1))
            }
        }
        return rows
    }

    /// Tap always opens Details, whatever the link count; the row's own affordances
    /// still reach every link explicitly.
    private func handleRowTap(_ entry: MiscEntry) {
        onShowDescription(DescriptionSheet.Payload(
            song: nil, version: entry.asSongVersion,
            artistName: artistName, artistSlug: artistSlug,
            eraName: entry.eraName, eraArt: eraArtUrl(for: entry.eraName)
        ))
    }

    /// Play an entry with continuation across every other streamable entry in the
    /// visible list. Non-audio links go straight to `onOpenLink`, which the row hands
    /// to the shared context menu.
    private func playEntry(_ entry: MiscEntry, in entries: [MiscEntry]) {
        Haptics.light()
        let streamable = entries.filter(\.isStreamable)
        guard let idx = streamable.firstIndex(where: { $0.id == entry.id }) else { return }
        let items = streamable.map {
            PlaybackListItem(
                version: $0.asSongVersion,
                artistName: artistName,
                eraName: $0.eraName,
                artUrl: eraArtUrl(for: $0.eraName) ?? "",
                artistSlug: artistSlug
            )
        }
        player.playInList(items, startAt: idx)
    }

    /// Era art for a misc entry — matched against the main-tab eras by name.
    private func eraArtUrl(for eraName: String) -> String? {
        eraArtByLowercasedName[eraName.lowercased()] ?? nil
    }
}

/// A content tab's sub-section label ("Instrumentals", "Music Videos").
private struct MiscSectionHeader: View {
    let name: String
    let displayColors: EraDisplayColors?

    var body: some View {
        Text(name)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(displayColors?.readableHeader ?? .secondary)
            .textCase(.uppercase)
            .tracking(0.5)
            .padding(.horizontal, 12)
            .padding(.top, 14)
            .padding(.bottom, 4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityAddTraits(.isHeader)
            .songPanel(displayColors, isLast: false)
    }
}
