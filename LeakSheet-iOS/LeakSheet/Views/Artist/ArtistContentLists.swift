import SwiftUI

/// The artist screen's content branches — one `View` type per mode
/// (filters, search, eras, content tabs, recents).
///
/// Split out of ArtistView.swift (2026-07-25). They were already
/// separate types on purpose: each takes narrow inputs so toggling one
/// mode doesn't share a SwiftUI invalidation boundary with the others
/// or with the screen's own @State. Only the file boundary is new.

// MARK: - Filter toggles

/// @Observable reference input — the narrow-inputs rule for value types
/// doesn't apply here; per-property observation tracking already scopes
/// this view's invalidation to exactly the flags it reads.
struct FilterTogglesView: View {
    let vm: ArtistViewModel

    static func tabIcon(for kind: String) -> String {
        switch kind {
        case "misc": return "film.stack"
        case "music_videos": return "video"
        case "released": return "music.note.list"
        case "best_of": return "star.circle"
        case "worst_of": return "hand.thumbsdown"
        case "stems": return "waveform.path"
        default: return "square.grid.2x2"
        }
    }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            // Sibling glass elements belong in one container — standalone
            // effects re-resolve independently and can trip the
            // "glassEffect() tried to update multiple times per frame" fault.
            GlassEffectContainer {
                HStack(spacing: 8) {
                    FilterChip(label: "Best Of", icon: "star.fill", isActive: vm.bestOf, tintColor: .filterBestOf) {
                        vm.toggleBestOf()
                    }
                    FilterChip(label: "Worst Of", icon: "hand.thumbsdown", isActive: vm.worstOf, tintColor: .filterBestOf) {
                        vm.toggleWorstOf()
                    }
                    FilterChip(label: "Grails", icon: "trophy.fill", isActive: vm.grails, tintColor: .filterGrail) {
                        vm.toggleGrails()
                    }
                    FilterChip(label: "Recent", icon: "clock", isActive: vm.recents, tintColor: .filterRecent) {
                        vm.toggleRecents()
                    }
                    FilterChip(label: "No Snippets", icon: "waveform.slash", isActive: vm.noSnippets, tintColor: .filterNoSnippets) {
                        vm.toggleNoSnippets()
                    }
                    if !vm.availableTabs.isEmpty {
                        // One chip per parsed content tab (Misc, Music
                        // Videos, Released, Best Of, Stems, …), labeled with
                        // the tracker's own tab name.
                        ForEach(vm.availableTabs) { tab in
                            FilterChip(
                                label: tab.name,
                                icon: Self.tabIcon(for: tab.kind),
                                isActive: vm.selectedTabKey == tab.id,
                                tintColor: .filterMisc
                            ) {
                                vm.selectTab(tab.id)
                            }
                        }
                    } else if vm.hasMiscEntries {
                        // Older cached payloads without `tabs` keep the
                        // legacy flat Misc chip.
                        FilterChip(label: "Misc", icon: "film.stack", isActive: vm.misc, tintColor: .filterMisc) {
                            vm.toggleMisc()
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
        }
    }
}

// MARK: - Search results

struct SearchResultsListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        let results = vm.content.searchResults
        if results.isEmpty {
            ContentUnavailableView.search(text: vm.content.state.query)
                .padding(.top, 40)
        } else {
            Text("\(results.count) result\(results.count == 1 ? "" : "s")")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16)
                .padding(.top, 4)
                .padding(.bottom, 4)

            ForEach(results) { result in
                SongRowView(
                    song: result.song,
                    version: result.version,
                    artistName: artistName,
                    artistSlug: artistSlug,
                    sourceUrl: sourceUrl,
                    eraName: result.era.name,
                    eraArt: result.era.artUrl,
                    showVersionBadge: true,
                    // Swipe-to-play must continue down the list like tap does,
                    // not stop after one track (missing onPlay fell back to a
                    // single-track play).
                    onPlay: { _ in
                        playWithinList(
                            results.map { (version: $0.version, era: $0.era, id: $0.id) },
                            tappedId: result.id
                        )
                    },
                    onShowDescription: onShowDescription
                )
                .contentShape(Rectangle())
                .accessibilityAddTraits(.isButton)
                .onTapGesture {
                    if result.version.isStreamable {
                        Haptics.light()
                        playWithinList(
                            results.map { (version: $0.version, era: $0.era, id: $0.id) },
                            tappedId: result.id
                        )
                    } else {
                        onShowDescription(DescriptionSheet.Payload(
                            song: result.song, version: result.version,
                            artistName: artistName, artistSlug: artistSlug,
                            eraName: result.era.name, eraArt: result.era.artUrl
                        ))
                    }
                }
                .padding(.horizontal, 16)
            }
        }
    }

    /// Start playback of the tapped entry inside its visible ordered list, so
    /// auto-advance continues down the list (search results) instead of
    /// stopping after one track.
    private func playWithinList(_ entries: [(version: SongVersion, era: Era, id: String)], tappedId: String) {
        let streamable = entries.filter { $0.version.isStreamable }
        guard let idx = streamable.firstIndex(where: { $0.id == tappedId }) else { return }
        let items = streamable.map {
            PlaybackListItem(
                version: $0.version,
                artistName: artistName,
                eraName: $0.era.name,
                artUrl: $0.era.artUrl ?? "",
                artistSlug: artistSlug
            )
        }
        player.playInList(items, startAt: idx)
    }
}

// MARK: - Eras list (flattened lazy rows)

struct ErasListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onShowDescription: (DescriptionSheet.Payload) -> Void
    let onColorExtracted: (Color) -> Void

    @Environment(PlayerViewModel.self) private var player
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var hasActiveFilters: Bool {
        // Must list EVERY chip that can empty the list, or the empty state
        // claims "No Songs" (tracker is empty) when the truth is "No Matches"
        // (your filter hid everything) — grails was missing.
        vm.bestOf || vm.worstOf || vm.grails || vm.noSnippets
    }

    var body: some View {
        if vm.eraRows.isEmpty {
            // Every other content branch (search/recents/misc) shows an empty
            // state; without this the eras branch rendered a blank void when a
            // filter (e.g. Best Of) removed every era.
            ContentUnavailableView {
                Label(
                    hasActiveFilters ? "No Matches" : "No Songs",
                    systemImage: hasActiveFilters ? "line.3.horizontal.decrease.circle" : "music.note.list"
                )
            } description: {
                Text(hasActiveFilters
                     ? "No songs match the current filters."
                     : "This tracker has no songs yet.")
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 48)
        } else {
            ForEach(vm.eraRows) { row in
                EraRowView(
                    row: row,
                    displayColors: vm.eraDisplay[row.eraName],
                    artistName: artistName,
                    artistSlug: artistSlug,
                    sourceUrl: sourceUrl,
                    onCardTap: { eraName in
                        withAnimation(reduceMotion ? nil : .spring(duration: 0.3, bounce: 0.1)) {
                            vm.toggleEra(eraName)
                        }
                    },
                    onColorExtracted: { eraName, color in
                        vm.setEraColor(eraName: eraName, dominant: color)
                        onColorExtracted(color)
                    },
                    onSongTap: handleSongTap,
                    onPlayVersion: playWithEraContext,
                    onShowDescription: onShowDescription
                )
            }
        }
    }

    /// Multi-version songs expand/collapse; single-version songs play (or
    /// show the description when not streamable).
    private func handleSongTap(_ song: Song, eraName: String, eraArt: String?, ordinal: Int) {
        if song.hasMultipleVersions {
            withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) {
                vm.toggleSongExpansion(eraName: eraName, ordinal: ordinal)
            }
        } else if let v = song.versions.first {
            if v.isStreamable {
                Haptics.light()
                playWithEraContext(v, eraName: eraName)
            } else {
                onShowDescription(DescriptionSheet.Payload(
                    song: song, version: v,
                    artistName: artistName, artistSlug: artistSlug,
                    eraName: eraName, eraArt: eraArt
                ))
            }
        }
    }

    /// Era-scoped playback: the filtered era's streamable versions are the
    /// auto-advance context (filtered-out versions are excluded, as before).
    private func playWithEraContext(_ version: SongVersion, eraName: String) {
        guard let filtered = vm.filteredEra(named: eraName) else { return }
        player.playInEra(
            version,
            eraName: eraName,
            artistName: artistName,
            artUrl: filtered.era.artUrl ?? "",
            versions: filtered.streamableVersions,
            artistSlug: artistSlug
        )
    }
}

// MARK: - Misc entries

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

    /// A minimal `Era` so a content-tab group renders through the same
    /// `EraCardView` as the main list. Only name and art matter here — the
    /// card reads nothing else, and the group's own entries are rendered
    /// below the card rather than from `sections`.
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
                ContentUnavailableView(
                    "No Misc Entries",
                    systemImage: "film.stack",
                    description: Text("Nothing matches the current filters.")
                )
                .padding(.top, 40)
            }
        } else {
            // Era-card accordion — literally the same EraCardView the main
            // eras list uses (glass, extracted era colors, cover art), so a
            // content tab is visually a page of the same app, not a
            // different-looking list. Groups are prebuilt off-main in the
            // filter pipeline (miscEraGroups).
            let groups = vm.content.miscEraGroups
            ForEach(groups) { group in
                let expanded = isExpanded(group.eraName, groupCount: groups.count)
                EraCardView(
                    era: eraForGroup(group),
                    expanded: expanded,
                    displayColors: vm.eraDisplay[group.eraName],
                    subtitle: "\(group.entries.count) entr\(group.entries.count == 1 ? "y" : "ies")",
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
                        vm.setEraColor(eraName: group.eraName, dominant: color)
                    }
                )
                .padding(.horizontal, 16)
                .padding(.top, 8)

                if isExpanded(group.eraName, groupCount: groups.count) {
                    ForEach(group.entries) { entry in
                        MiscEntryRowView(
                            entry: entry,
                            onShowDescription: onShowDescription,
                            onSelectLink: { link in handleLinkSelection(link, for: entry, in: entries) }
                        )
                        .contentShape(Rectangle())
                        .accessibilityAddTraits(.isButton)
                        .onTapGesture {
                            handleRowTap(entry, in: entries)
                        }
                        .padding(.horizontal, 16)
                    }
                }
            }
        }
    }

    /// A single link is unambiguous, so the row's own tap performs it
    /// directly. Zero or multiple links have no one obvious action — the
    /// description sheet is the safe default, and the row's menu (built from
    /// `entry.mediaLinks`) lets the user pick a specific link explicitly.
    private func handleRowTap(_ entry: MiscEntry, in entries: [MiscEntry]) {
        let links = entry.mediaLinks
        if links.count == 1 {
            handleLinkSelection(links[0], for: entry, in: entries)
        } else {
            onShowDescription(DescriptionSheet.Payload(
                song: nil, version: entry.asSongVersion,
                artistName: artistName, artistSlug: artistSlug,
                eraName: entry.eraName, eraArt: eraArtUrl(for: entry.eraName)
            ))
        }
    }

    /// Stream-kind links play with continuation across every other
    /// stream-kind entry in the visible list, matching era/song playback;
    /// everything else (image, video, archive, generic link) opens
    /// externally — the OS decides how to handle it (Safari, a video app, a
    /// zip download).
    private func handleLinkSelection(_ link: MiscLink, for entry: MiscEntry, in entries: [MiscEntry]) {
        switch link.kind {
        case .stream:
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
        case .image, .video, .embed, .archive, .link:
            onOpenLink(link)
        }
    }

    /// Era art for a misc entry — matched against the main-tab eras by name.
    private func eraArtUrl(for eraName: String) -> String? {
        eraArtByLowercasedName[eraName.lowercased()] ?? nil
    }
}

// MARK: - Recents

struct RecentsListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        let visible = vm.visibleRecents

        if visible.isEmpty {
            if vm.isFiltering {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 32)
            } else {
                ContentUnavailableView(
                    "No Recent Leaks",
                    systemImage: "clock",
                    description: Text("No versions carry a leak or file date.")
                )
                .padding(.top, 40)
            }
        } else {
            ForEach(Array(visible.enumerated()), id: \.element.id) { idx, result in
                // Era group header — show when era changes
                if idx == 0 || visible[idx - 1].era.name != result.era.name {
                    HStack(spacing: 8) {
                        Text(result.era.name.uppercased())
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(vm.eraDisplay[result.era.name]?.readableHeader ?? .secondary)
                        Rectangle()
                            .fill(Color.lsBorder)
                            .frame(height: 1)
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, idx == 0 ? 4 : 12)
                    .padding(.bottom, 2)
                }

                // Date label — show only when different from previous
                let prevDate = idx > 0 ? (visible[idx - 1].version.leakDate ?? visible[idx - 1].version.fileDate) : nil
                let thisDate = result.version.leakDate ?? result.version.fileDate
                if let date = thisDate, !date.isEmpty, date != prevDate {
                    HStack(spacing: 4) {
                        Image(systemName: "calendar")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        Text(date)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                        Spacer()
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 4)
                }

                SongRowView(
                    song: result.song,
                    version: result.version,
                    artistName: artistName,
                    artistSlug: artistSlug,
                    sourceUrl: sourceUrl,
                    eraName: result.era.name,
                    eraArt: result.era.artUrl,
                    showVersionBadge: true,
                    // Swipe-to-play continues down the recents list like tap.
                    onPlay: { _ in
                        if let (items, idx) = vm.recentPlayback(for: result.id) {
                            player.playInList(items, startAt: idx)
                        }
                    },
                    onShowDescription: onShowDescription
                )
                .contentShape(Rectangle())
                .accessibilityAddTraits(.isButton)
                .onTapGesture {
                    if result.version.isStreamable {
                        Haptics.light()
                        // Prebuilt playback list continues down the FULL
                        // recents list, not just the rendered window.
                        if let (items, idx) = vm.recentPlayback(for: result.id) {
                            player.playInList(items, startAt: idx)
                        }
                    } else {
                        onShowDescription(DescriptionSheet.Payload(
                            song: result.song, version: result.version,
                            artistName: artistName, artistSlug: artistSlug,
                            eraName: result.era.name, eraArt: result.era.artUrl
                        ))
                    }
                }
                .padding(.horizontal, 16)
                .onAppear {
                    if idx == visible.count - 1 {
                        vm.loadMoreRecents()
                    }
                }
            }
        }
    }
}

