import SwiftUI

/// The artist screen, on the phone's `ArtistViewModel`: eras are expandable sections
/// in one column, because the focus engine walks rows rather than tapping headers.
struct TVArtistView: View {
    let artist: Artist
    var notice: String?

    @Environment(RecentTrackersManager.self) private var recents

    @State private var viewModel: ArtistViewModel?
    @State private var refresher = TrackerLoader()
    @State private var showStats = false
    @State private var showLegend = false

    var body: some View {
        Group {
            if let viewModel {
                content(viewModel)
            } else {
                ProgressView("Preparing…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Color.lsBackground)
        .navigationTitle(artist.name)
        .onChange(of: viewModel?.eraPlaybackRevision) {
            if let viewModel { PlayerViewModel.shared.setArtistEras(viewModel.eraPlaybackContexts) }
        }
        // Keyed on the view model, as on iOS: a refresh swaps in a new one, which must
        // re-register its eras instead of leaving the old song lists.
        .task(id: viewModel.map { ObjectIdentifier($0) }) {
            if let viewModel {
                // Era rollover needs the artist's era list, as on iOS and macOS.
                PlayerViewModel.shared.setArtistEras(viewModel.eraPlaybackContexts)
            } else {
                // Setting viewModel changes the id, so this task runs again to register it.
                let made = await ArtistViewModel.make(artist: artist)
                made.loadNotice = notice
                viewModel = made
            }
        }
    }

    @ViewBuilder
    private func content(_ viewModel: ArtistViewModel) -> some View {
        @Bindable var viewModel = viewModel
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 20) {
                statsBar(viewModel)
                if let notice = viewModel.loadNotice {
                    Text(notice)
                        .font(.caption)
                        .foregroundStyle(Color.lsError)
                        .frame(maxWidth: .infinity)
                }
                filterChips(viewModel)

                if viewModel.isSearching {
                    searchResults(viewModel)
                } else {
                    ForEach(viewModel.content.eras) { filtered in
                        eraSection(filtered, viewModel: viewModel)
                    }
                }
            }
            .padding(.vertical, 32)
        }
        .searchable(text: $viewModel.searchQuery, prompt: "Search songs…")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Stats") { showStats = true }
            }
            ToolbarItem(placement: .primaryAction) {
                Button("Badges") { showLegend = true }
            }
            ToolbarItem(placement: .primaryAction) {
                // tvOS has no pull-to-refresh gesture, so refresh is explicit.
                Button {
                    Task { await refresh() }
                } label: {
                    if refresher.loading { ProgressView() } else { Text("Refresh") }
                }
                .disabled(refresher.loading)
            }
        }
        .sheet(isPresented: $showStats) { TVStatsView(artist: viewModel.artist, stats: viewModel.artistStats) }
        .sheet(isPresented: $showLegend) { TVBadgeLegendView() }
    }

    // MARK: - Header

    private func statsBar(_ viewModel: ArtistViewModel) -> some View {
        HStack(spacing: 56) {
            // .formatted(): `stat` takes a String, which skips the locale
            // grouping Text applies to a bare Int.
            stat(viewModel.artistStats.total.formatted(), "Total", .primary)
            stat(viewModel.artistStats.available.formatted(), "Available", .green)
            stat(viewModel.artistStats.snippets.formatted(), "Snippets", .orange)
            stat(viewModel.artistStats.fullHQ.formatted(), "Full HQ", Color.lsPrimary)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 60)
    }

    private func stat(_ value: String, _ label: String, _ tint: Color) -> some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.title2.bold().monospacedDigit())
                .foregroundStyle(tint)
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func filterChips(_ viewModel: ArtistViewModel) -> some View {
        ScrollView(.horizontal) {
            HStack(spacing: 16) {
                // Through the toggle methods, which re-run the filter and keep the badge filters
                // exclusive. No "Recent" chip: this screen has no recents list.
                chip("Best Of", "star", isOn: viewModel.bestOf, action: viewModel.toggleBestOf)
                chip("Worst Of", "hand.thumbsdown", isOn: viewModel.worstOf, action: viewModel.toggleWorstOf)
                chip("Grails", "trophy", isOn: viewModel.grails, action: viewModel.toggleGrails)
                chip("No Snippets", "scissors", isOn: viewModel.noSnippets, action: viewModel.toggleNoSnippets)
            }
            .padding(.horizontal, 60)
            .padding(.vertical, 8)
        }
        .scrollClipDisabled()
        // Keeps left/right on the chip row from escaping into the song list.
        .focusSection()
    }

    private func chip(_ title: String, _ symbol: String, isOn: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.callout)
                .padding(.horizontal, 22)
                .padding(.vertical, 12)
                .background(isOn ? Color.lsPrimary.opacity(0.28) : Color.lsCard)
                .clipShape(Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    // MARK: - Content branches

    @ViewBuilder
    private func eraSection(_ filtered: FilteredEra, viewModel: ArtistViewModel) -> some View {
        let era = filtered.era
        let isExpanded = viewModel.expandedEra == era.name
        let songs = filtered.sections.isEmpty
            ? filtered.songs
            : filtered.sections.flatMap(\.songs)

        VStack(alignment: .leading, spacing: 10) {
            Button {
                viewModel.expandedEra = isExpanded ? nil : era.name
            } label: {
                HStack(spacing: 20) {
                    eraArt(era)
                    VStack(alignment: .leading, spacing: 6) {
                        Text(era.name)
                            .font(.title3.weight(.semibold))
                            .lineLimit(2)
                        Text("\(filtered.stats.total) versions · \(filtered.stats.available) available")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 14)
                .contentShape(Rectangle())
            }
            .buttonStyle(TVRowButtonStyle())
            .padding(.horizontal, 36)

            if isExpanded {
                // `offset` in the id, not baseName: several distinct "???" songs per era would
                // collide in ForEach (the same reason EraRow.id carries an ordinal).
                LazyVStack(spacing: 10) {
                    ForEach(Array(songs.enumerated()), id: \.offset) { _, song in
                        TVSongRowView(
                            song: song,
                            eraName: era.name,
                            eraArt: era.artUrl,
                            artist: viewModel.artist,
                            eraSongs: songs
                        )
                    }
                }
            }
        }
        // One focus group per era, so up/down walks this era's songs before
        // stepping out to the neighbouring era headers.
        .focusSection()
    }

    @ViewBuilder
    private func eraArt(_ era: Era) -> some View {
        if let art = era.artUrl, let url = APIClient.shared.imageProxyURL(for: art, width: 320) {
            CachedImage(url: url, maxPixelSize: 320) {
                ArtworkPlaceholder(cornerRadius: 10)
            }
            .frame(width: 110, height: 110)
            .clipShape(RoundedRectangle(cornerRadius: 10))
        } else {
            ArtworkPlaceholder(cornerRadius: 10)
                .frame(width: 110, height: 110)
        }
    }

    @ViewBuilder
    private func searchResults(_ viewModel: ArtistViewModel) -> some View {
        if viewModel.content.searchResults.isEmpty {
            ContentUnavailableView.search(text: viewModel.searchQuery)
                .padding(.top, 60)
        } else {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(viewModel.content.searchResults) { result in
                    TVVersionRowView(
                        version: result.version,
                        song: result.song,
                        eraName: result.era.name,
                        eraArt: result.era.artUrl,
                        artist: viewModel.artist
                    )
                }
            }
            .focusSection()
        }
    }

    // MARK: - Refresh

    /// As on iOS: a failed or cache-served refresh keeps the current data and says why.
    private func refresh() async {
        guard let url = artist.sourceUrl else { return }
        let fresh = await refresher.load(url, artistName: artist.name, forceRefresh: true, recents: recents)
        guard let fresh, refresher.staleNotice == nil else {
            if let notice = refresher.error ?? refresher.staleNotice { viewModel?.loadNotice = notice }
            return
        }
        viewModel = await ArtistViewModel.make(artist: fresh)
    }
}
