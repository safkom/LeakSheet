#if os(macOS)
import SwiftUI

extension MacArtistView {
    // MARK: - Page header

    /// Scrolls with the content rather than sitting above it, where it took ~290pt
    /// of a 700pt window.
    @ViewBuilder
    var pageHeader: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let openEra {
                eraHeader(openEra)
            } else {
                trackerHeader
            }

            // FlowLayout, not a horizontal scroller: a Mac shows no scroll affordance on an
            // indicator-less strip, so chips past the fold would be invisible.
            FlowLayout(spacing: 8) {
                MacFilterChip(
                    label: "Best Of",
                    icon: "star.fill",
                    isActive: vm.bestOf,
                    tint: .filterBestOf
                ) { vm.toggleBestOf() }
                MacFilterChip(
                    label: "Worst Of",
                    icon: "hand.thumbsdown",
                    isActive: vm.worstOf,
                    tint: .filterWorstOf
                ) { vm.toggleWorstOf() }
                MacFilterChip(
                    label: "Grails",
                    icon: "trophy.fill",
                    isActive: vm.grails,
                    tint: .filterGrail
                ) { vm.toggleGrails() }
                MacFilterChip(
                    label: "Recent",
                    icon: "clock",
                    isActive: vm.recents,
                    tint: .filterRecent
                ) { vm.toggleRecents() }
                MacFilterChip(
                    label: "No Snippets",
                    icon: "waveform.slash",
                    isActive: vm.noSnippets,
                    tint: .filterNoSnippets
                ) { vm.toggleNoSnippets() }
                ForEach(vm.availableTabs) { tab in
                    MacFilterChip(
                        label: ContentTabsView.labelText(for: tab.name),
                        icon: ContentTabsView.tabIcon(for: tab.kind),
                        isActive: vm.selectedTabKey == tab.id,
                        tint: .filterMisc
                    ) { vm.selectTab(tab.id) }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .padding(.bottom, 10)
    }

    /// Tracker-level chrome, shown on the era grid.
    @ViewBuilder
    private var trackerHeader: some View {
        if let notices = artist.notices, !notices.isEmpty {
            VStack(spacing: 4) {
                ForEach(notices) { notice in
                    NoticeBannerView(notice: notice) { safariItem = SafariItem(url: $0) }
                }
            }
        }
        statRow(vm.artistStats)
        if let notice = vm.loadNotice {
            Text(notice)
                .font(.caption2)
                .foregroundStyle(Color.lsError)
        } else if let lastUpdated {
            TimelineView(.periodic(from: .now, by: 15)) { _ in
                Text("Updated \(lastUpdated.formatted(.relative(presentation: .named)))")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func eraCover(_ artUrl: String?) -> some View {
        Group {
            if let artUrl, let url = APIClient.shared.imageProxyURL(for: artUrl, width: 240) {
                CachedImage(url: url, maxPixelSize: 240) { ArtworkPlaceholder(cornerRadius: 0) }
            } else {
                ArtworkPlaceholder(cornerRadius: 0)
            }
        }
        .frame(width: 72, height: 72)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func eraTitles(_ name: String, _ filtered: FilteredEra?) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(name)
                .font(.title2.weight(.semibold))
                .lineLimit(2)
            if let alts = filtered?.era.altNames, !alts.isEmpty {
                Text(alts.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            if let stats = filtered?.stats {
                Text("\(stats.total) tracks · \(stats.available) available · \(stats.snippets) snippets")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// Era-level chrome: cover, name, the era's own numbers, and a Play action.
    @ViewBuilder
    private func eraHeader(_ name: String) -> some View {
        let filtered = vm.filteredEra(named: name)
        HStack(alignment: .center, spacing: 14) {
            eraCover(filtered?.era.artUrl)
            eraTitles(name, filtered)

            Spacer(minLength: 8)

            Button {
                showEraInfo(name)
            } label: {
                Image(systemName: "info.circle")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("\(name) info")
            .help("About this era")

            if let filtered, !filtered.streamableVersions.isEmpty {
                Button {
                    player.playEra(filtered, artistName: artist.name, artistSlug: artist.slug)
                } label: {
                    Label("Play", systemImage: "play.fill")
                }
                .buttonStyle(.borderedProminent)
                .help("Play this era")
            }
        }

        if let desc = filtered?.era.description, !desc.isEmpty {
            Text(desc)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// Compact stat row, not a set of full-width tiles.
    private func statRow(_ stats: ArtistViewModel.Stats) -> some View {
        HStack(spacing: 8) {
            statTile(stats.total, "Total", .secondary)
            statTile(stats.available, "Available", Color.lsSuccess)
            statTile(stats.snippets, "Snippets", Color.lsWarning)
            statTile(stats.fullHQ, "Full HQ", .lsAccent)
        }
    }

    @ViewBuilder
    private func statTile(_ value: Int, _ label: String, _ color: Color) -> some View {
        if artist.trackerStats != nil {
            Button { showStats = true } label: { statTileBody(value, label, color) }
                .buttonStyle(.plain)
                .help("Show tracker stats")
        } else {
            statTileBody(value, label, color)
        }
    }

    private func statTileBody(_ value: Int, _ label: String, _ color: Color) -> some View {
        VStack(spacing: 1) {
            Text("\(value)")
                .font(.subheadline.weight(.semibold).monospacedDigit())
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(minWidth: 76)
        .padding(.vertical, 6)
        .background(Color.lsCard, in: RoundedRectangle(cornerRadius: 8))
    }

    @ToolbarContentBuilder
    var toolbarItems: some ToolbarContent {
        ToolbarItemGroup {
            if openEra != nil {
                Button {
                    vm.openEra(nil)
                    ui.selectedSong = nil
                } label: {
                    Label("All Eras", systemImage: "chevron.backward")
                }
                .keyboardShortcut("[", modifiers: .command)
                .help("Back to all eras (⌘[)")
            }

            Menu {
                if artist.trackerStats != nil {
                    Button { showStats = true } label: { Label("Stats", systemImage: "chart.bar.xaxis") }
                }
                if hasTimeline {
                    Button { showTimeline = true } label: { Label("Timeline", systemImage: "clock") }
                }
                Button { showLegend = true } label: { Label("Badge Legend", systemImage: "info.circle") }
                Button { player.playNewestLeaks(vm.artist) } label: {
                    Label("Newest Leaks", systemImage: "clock.arrow.circlepath")
                }
            } label: {
                Label("More", systemImage: "ellipsis")
            }

            Button {
                ui.inspectorTab = .queue
                ui.showInspector = true
            } label: {
                Label("Queue", systemImage: "list.bullet")
            }
            .help("Show the queue")
        }
    }
}
#endif
