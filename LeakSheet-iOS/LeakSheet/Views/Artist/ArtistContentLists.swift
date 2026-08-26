import SwiftUI

/// The artist screen's content branches — one `View` type per mode
/// (filters, search, eras, content tabs, recents).
///
/// Split out of ArtistView.swift (2026-07-25). They were already
/// separate types on purpose: each takes narrow inputs so toggling one
/// mode doesn't share a SwiftUI invalidation boundary with the others
/// or with the screen's own @State. Only the file boundary is new.

// MARK: - Content tabs

/// The tracker's pages: the song tree plus one chip per parsed content tab.
/// Exactly one is active at a time.
///
/// Split out of the filter row. Both were one scrolling strip of identical
/// chips, so "Grails" and "Released" looked like the same kind of control while
/// doing fundamentally different things — a filter annotates the list you are
/// on, a tab replaces it. `selectTab` already clears the badge filters when a
/// tab is chosen, which is the same statement in code.
struct ContentTabsView: View {
    let vm: ArtistViewModel

    /// Icon for a content-tab chip. Badge-annotation kinds (best_of, worst_of,
    /// …) never reach here — `availableTabs` filters them out because they are
    /// annotation sources, not pages — so they have no arms.
    static func tabIcon(for kind: String) -> String {
        switch kind {
        case "misc": return "film.stack"
        case "music_videos": return "video"
        case "released": return "music.note.list"
        case "stems": return "waveform.path"
        default: return "square.grid.2x2"
        }
    }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            GlassEffectContainer {
                HStack(spacing: 8) {
                    // The song tree. Named for what these trackers call it —
                    // the filters beside it (Grails, Snippets, Best Of) are all
                    // unreleased-leak concepts.
                    FilterChip(
                        label: "Unreleased",
                        icon: "waveform",
                        isActive: vm.selectedTabKey == nil,
                        tintColor: .lsAccent
                    ) {
                        vm.selectTab(nil)
                    }
                    if !vm.availableTabs.isEmpty {
                        ForEach(vm.availableTabs) { tab in
                            FilterChip(
                                label: tab.name,
                                icon: Self.tabIcon(for: tab.kind),
                                isActive: vm.selectedTabKey == tab.id,
                                tintColor: .lsAccent
                            ) {
                                vm.selectTab(tab.id)
                            }
                        }
                    } else if vm.hasMiscEntries {
                        // Older cached payloads without `tabs` keep the
                        // legacy flat Misc chip.
                        FilterChip(label: "Misc", icon: "film.stack", isActive: vm.misc, tintColor: .lsAccent) {
                            vm.toggleMisc()
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
        }
        .accessibilityLabel("Tracker sections")
    }
}

// MARK: - Filter toggles

/// Badge filters over the song tree. Multi-select, and only meaningful on the
/// song tree — a content tab lists entries, which carry no badges — so the
/// caller hides this row entirely while a tab is selected rather than showing
/// controls that would silently do nothing.
///
/// @Observable reference input — the narrow-inputs rule for value types
/// doesn't apply here; per-property observation tracking already scopes
/// this view's invalidation to exactly the flags it reads.
struct FilterTogglesView: View {
    let vm: ArtistViewModel

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
                }
            }
            .padding(.horizontal, 16)
        }
        .accessibilityLabel("Filters")
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

            ForEach(Array(results.enumerated()), id: \.element.id) { idx, result in
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
                // Tap opens Details, never plays — see handleSongTap.
                .onTapGesture {
                    onShowDescription(DescriptionSheet.Payload(
                        song: result.song, version: result.version,
                        artistName: artistName, artistSlug: artistSlug,
                        eraName: result.era.name, eraArt: result.era.artUrl
                    ))
                }
                // Same tinted panel the eras branch uses, so a search result
                // reads as the same kind of object as the row it came from.
                // The tail rounds where the era changes.
                .songPanel(
                    vm.eraDisplay[result.era.name],
                    isLast: idx == results.count - 1
                        || results[idx + 1].era.name != result.era.name
                )
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

    /// Multi-version songs expand/collapse; single-version songs open Details.
    ///
    /// Tap used to start playback, which made an accidental brush of the list
    /// hijack whatever was playing. Play is still one gesture away: swipe from
    /// the leading edge, long-press → Play, the three-dot menu, or the Play
    /// button inside Details.
    private func handleSongTap(_ song: Song, eraName: String, eraArt: String?, ordinal: Int) {
        if song.hasMultipleVersions {
            withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) {
                vm.toggleSongExpansion(eraName: eraName, ordinal: ordinal)
            }
        } else if let v = song.versions.first {
            onShowDescription(DescriptionSheet.Payload(
                song: song, version: v,
                artistName: artistName, artistSlug: artistSlug,
                eraName: eraName, eraArt: eraArt
            ))
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

    /// Normalised key for `vm.eraDisplay`.
    ///
    /// The card renders "Other" for an empty era name and matches its art
    /// case-insensitively, but colours were stored and read under the RAW
    /// name — so an empty-named group loaded its cover and then rendered
    /// uncoloured, and any casing difference against the main-tab era did the
    /// same. Reads and writes now agree on one key.
    private func colorKey(_ eraName: String) -> String {
        eraName.isEmpty ? "Other" : eraName
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
                // Name the page the user is actually on: this branch renders
                // every content tab, so a filtered-empty Stems page announced
                // "No Misc Entries".
                ContentUnavailableView(
                    "No \(vm.selectedTabName ?? "Misc") Entries",
                    systemImage: "film.stack",
                    description: Text("Nothing matches the current filters.")
                )
                .padding(.top, 40)
            }
        } else {
            // Shared EraCardView — see DECISIONS.md::ArtistContentLists.swift::era-card-reuse
            let groups = vm.content.miscEraGroups
            ForEach(groups) { group in
              // Single root — same LazyVStack identity-templating rule the
              // eras branch follows (see ArtistRowViews.swift).
              VStack(spacing: 0) {
                let expanded = isExpanded(group.eraName, groupCount: groups.count)
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

                if isExpanded(group.eraName, groupCount: groups.count) {
                    ForEach(Array(group.entries.enumerated()), id: \.element.id) { idx, entry in
                        MiscEntryRowView(
                            entry: entry,
                            onShowDescription: onShowDescription,
                            onSelectLink: { link in handleLinkSelection(link, for: entry, in: entries) }
                        )
                        .contentShape(Rectangle())
                        .accessibilityAddTraits(.isButton)
                        .onTapGesture { handleRowTap(entry) }
                        // Content tabs used to render bare rows against the app
                        // background under a card whose border opens at the
                        // bottom to flush into a panel that wasn't there.
                        .songPanel(
                            vm.eraDisplay[colorKey(group.eraName)],
                            isLast: idx == group.entries.count - 1
                        )
                    }
                }
              }
            }
        }
    }

    /// Tap always opens Details, whatever the link count.
    ///
    /// A single link used to be performed directly, so a stray tap started a
    /// stream or bounced the user into Safari. The row's own affordances (the
    /// trailing link control, the menu built from `entry.mediaLinks`) and the
    /// sheet itself still reach every link explicitly.
    private func handleRowTap(_ entry: MiscEntry) {
        onShowDescription(DescriptionSheet.Payload(
            song: nil, version: entry.asSongVersion,
            artistName: artistName, artistSlug: artistSlug,
            eraName: entry.eraName, eraArt: eraArtUrl(for: entry.eraName)
        ))
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
              // Single root: LazyVStack can only template row identity from
              // the ForEach ids when the body is unary — the eras branch was
              // restructured for exactly this (see ArtistRowViews.swift), and
              // this branch never was.
              VStack(spacing: 0) {
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
                // Tap opens Details, never plays — see handleSongTap.
                .onTapGesture {
                    onShowDescription(DescriptionSheet.Payload(
                        song: result.song, version: result.version,
                        artistName: artistName, artistSlug: artistSlug,
                        eraName: result.era.name, eraArt: result.era.artUrl
                    ))
                }
                // Same tinted panel as the eras branch; the tail rounds where
                // the era group ends.
                .songPanel(
                    vm.eraDisplay[result.era.name],
                    isLast: idx == visible.count - 1
                        || visible[idx + 1].era.name != result.era.name
                )
                .onAppear {
                    // Against the LIVE count, not the `visible` snapshot this
                    // body closed over — a fast scroll fired several appends
                    // off one stale count. Eight rows early so the next page
                    // is in place before the user reaches the end.
                    if idx >= vm.visibleRecents.count - 8 {
                        vm.loadMoreRecents()
                    }
                }
              }
            }
        }
    }
}

