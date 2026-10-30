import Foundation
import SwiftUI
import Observation

extension ArtistViewModel {
    // MARK: - Era expand/collapse

    func toggleEra(_ name: String) {
        if isBadgeFilterActive { return }
        expandedEra = expandedEra == name ? nil : name
        rebuildEraRows()
    }

    /// Set (or clear) the single expanded era outright, whatever was open before
    /// (`toggleEra` flips).
    func openEra(_ name: String?) {
        guard !isBadgeFilterActive, expandedEra != name else { return }
        expandedEra = name
        rebuildEraRows()
    }

    func isEraExpanded(_ name: String) -> Bool {
        if isBadgeFilterActive { return true }
        return expandedEra == name
    }

    func isSongExpanded(eraName: String, ordinal: Int) -> Bool {
        expandedSongs.contains("\(eraName)::\(ordinal)")
    }

    func toggleSongExpansion(eraName: String, ordinal: Int) {
        // Keyed by positional ordinal, not baseName, so expanding one of
        // several same-named ("???") songs doesn't expand its siblings.
        let key = "\(eraName)::\(ordinal)"
        if expandedSongs.contains(key) {
            expandedSongs.remove(key)
        } else {
            expandedSongs.insert(key)
        }
        rebuildEraRows()
    }

    /// The filtered era backing a row — era-scoped playback context.
    func filteredEra(named name: String) -> FilteredEra? {
        content.eras.first { $0.era.name == name }
    }

    func toggleBestOf() {
        bestOf.toggle()
        // The badge filters are mutually exclusive — enabling one clears the
        // others so the AND pipeline never intersects two badge sets.
        if bestOf { worstOf = false; grails = false }
        if !isBadgeFilterActive && !recents { expandedEra = nil }
        // No sync rebuildEraRows() here — see DECISIONS.md::ArtistViewModel.swift::no-sync-rebuild
        applyFilters()
    }

    func toggleWorstOf() {
        worstOf.toggle()
        if worstOf { bestOf = false; grails = false }
        if !isBadgeFilterActive && !recents { expandedEra = nil }
        applyFilters()
    }

    func toggleGrails() {
        grails.toggle()
        if grails { bestOf = false; worstOf = false }
        if !isBadgeFilterActive && !recents { expandedEra = nil }
        applyFilters()
    }

    func toggleRecents() {
        recents.toggle()
        if !recents {
            if !isBadgeFilterActive { expandedEra = nil }
            rebuildEraRows()
        }
        applyFilters()
    }

    func toggleNoSnippets() {
        noSnippets.toggle()
        applyFilters()
    }

    /// Selects a content tab (tapping the active chip deselects it).
    /// Entering a tab resets the filter chips — except No Snippets, which
    /// keeps excluding short clips on every page.
    func selectTab(_ key: String?) {
        selectedTabKey = (selectedTabKey == key) ? nil : key
        if selectedTabKey != nil {
            bestOf = false
            worstOf = false
            grails = false
            recents = false
        }
        if selectedTabKey == nil && !isBadgeFilterActive && !recents {
            expandedEra = nil
            rebuildEraRows()
        }
        applyFilters()
    }

    // MARK: - Row building (main thread, cheap appends only)

    func rebuildEraRows() {
        var rows: [EraRow] = []
        rows.reserveCapacity(content.eras.count * 3)
        for filtered in content.eras {
            let eraName = filtered.era.name
            let eraArt = filtered.era.artUrl
            let expanded = isEraExpanded(eraName)
            rows.append(.card(filtered, expanded: expanded))
            if expanded {
                rows.append(.divider(eraName: eraName))
                let startCount = rows.count
                // One running ordinal across all sections of the era so every
                // song row has a unique positional identity within the era.
                var ordinal = 0
                if filtered.sections.isEmpty {
                    appendSongRows(&rows, songs: filtered.songs, eraName: eraName, eraArt: eraArt, ordinal: &ordinal)
                } else {
                    var previousGroup: String?
                    var seen: [String: Int] = [:]
                    for section in filtered.sections {
                        // The parser stamps the group on every section under it: one header per run.
                        let startsRun = section.group != nil && section.group != previousGroup
                        if startsRun, let group = section.group {
                            let key = "grp:\(group)"
                            rows.append(.groupHeader(text: group, eraName: eraName, occurrence: seen[key, default: 0]))
                            seen[key, default: 0] += 1
                        }
                        previousGroup = section.group
                        if !section.name.isEmpty {
                            let key = "sec:\(section.group ?? ""):\(section.name)"
                            // `group` only when a group header sits directly above (tighter spacing).
                            rows.append(.sectionHeader(
                                name: section.name, eraName: eraName, group: startsRun ? section.group : nil,
                                occurrence: seen[key, default: 0], notes: section.notes
                            ))
                            seen[key, default: 0] += 1
                        }
                        appendSongRows(&rows, songs: section.songs, eraName: eraName, eraArt: eraArt, ordinal: &ordinal)
                    }
                }
                // Mark the era's final content row for bottom-corner rounding.
                if rows.count > startCount {
                    rows[rows.count - 1] = markedLast(rows[rows.count - 1])
                }
            }
            rows.append(.eraGap(eraName: eraName))
        }
        eraRows = rows
    }

    private func appendSongRows(
        _ rows: inout [EraRow],
        songs: [Song],
        eraName: String,
        eraArt: String?,
        ordinal: inout Int
    ) {
        for song in songs {
            let hasMultiple = song.hasMultipleVersions
            let expanded = hasMultiple && isSongExpanded(eraName: eraName, ordinal: ordinal)
            rows.append(.song(
                song, eraName: eraName, eraArt: eraArt,
                expanded: expanded, hasMultiple: hasMultiple, isLast: false, ordinal: ordinal
            ))
            if expanded {
                // `versions` (what matched the filter): the array the row's count and chevron use.
                // Playback context uses `allVersions` elsewhere, so auto-advance is unaffected.
                for (idx, version) in song.versions.enumerated() {
                    rows.append(.version(
                        version, index: idx, song: song,
                        eraName: eraName, eraArt: eraArt, isLast: false, songOrdinal: ordinal
                    ))
                }
            }
            ordinal += 1
        }
    }

    private func markedLast(_ row: EraRow) -> EraRow {
        switch row {
        case .song(let song, let eraName, let eraArt, let expanded, let hasMultiple, _, let ordinal):
            return .song(song, eraName: eraName, eraArt: eraArt,
                         expanded: expanded, hasMultiple: hasMultiple, isLast: true, ordinal: ordinal)
        case .version(let version, let index, let song, let eraName, let eraArt, _, let songOrdinal):
            return .version(version, index: index, song: song,
                            eraName: eraName, eraArt: eraArt, isLast: true, songOrdinal: songOrdinal)
        default:
            return row
        }
    }
}
