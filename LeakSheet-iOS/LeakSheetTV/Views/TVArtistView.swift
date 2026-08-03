import SwiftUI

/// The artist screen. Uses the same `ArtistViewModel` and `FilterPipeline` the
/// phone does — only the presentation differs: eras are expandable sections in
/// one vertical column rather than a card list, because the focus engine walks
/// rows and columns rather than responding to taps on headers.
struct TVArtistView: View {
    let artist: Artist

    @Environment(RecentTrackersManager.self) private var recents

    @State private var vm: ArtistViewModel?
    @State private var refreshing = false
    @State private var showStats = false
    @State private var showLegend = false

    var body: some View {
        Group {
            if let vm {
                content(vm)
            } else {
                ProgressView("Preparing…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Color.lsBackground)
        .navigationTitle(artist.name)
        .task {
            if vm == nil { vm = await ArtistViewModel.make(artist: artist) }
        }
    }

    @ViewBuilder
    private func content(_ vm: ArtistViewModel) -> some View {
        @Bindable var vm = vm
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 20) {
                statsBar(vm)
                filterChips(vm)

                if vm.isSearching {
                    searchResults(vm)
                } else {
                    ForEach(vm.content.eras) { filtered in
                        eraSection(filtered, vm: vm)
                    }
                    if !vm.content.miscResults.isEmpty {
                        miscSection(vm)
                    }
                }
            }
            .padding(.vertical, 32)
        }
        .searchable(text: $vm.searchQuery, prompt: "Search songs…")
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
                    if refreshing { ProgressView() } else { Text("Refresh") }
                }
                .disabled(refreshing)
            }
        }
        .sheet(isPresented: $showStats) { TVStatsView(artist: vm.artist, stats: vm.artistStats) }
        .sheet(isPresented: $showLegend) { TVBadgeLegendView() }
    }

    // MARK: - Header

    private func statsBar(_ vm: ArtistViewModel) -> some View {
        HStack(spacing: 56) {
            stat("\(vm.artistStats.total)", "Total", .primary)
            stat("\(vm.artistStats.available)", "Available", .green)
            stat("\(vm.artistStats.snippets)", "Snippets", .orange)
            stat("\(vm.artistStats.fullHQ)", "Full HQ", Color.lsPrimary)
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

    private func filterChips(_ vm: ArtistViewModel) -> some View {
        @Bindable var vm = vm
        return ScrollView(.horizontal) {
            HStack(spacing: 16) {
                chip("Best Of", "star", isOn: $vm.bestOf)
                chip("Worst Of", "hand.thumbsdown", isOn: $vm.worstOf)
                chip("Grails", "trophy", isOn: $vm.grails)
                chip("Recent", "clock", isOn: $vm.recents)
                chip("No Snippets", "scissors", isOn: $vm.noSnippets)
            }
            .padding(.horizontal, 60)
            .padding(.vertical, 8)
        }
        .scrollClipDisabled()
        // Keeps left/right on the chip row from escaping into the song list.
        .focusSection()
    }

    private func chip(_ title: String, _ symbol: String, isOn: Binding<Bool>) -> some View {
        Button {
            isOn.wrappedValue.toggle()
        } label: {
            Label(title, systemImage: symbol)
                .font(.callout)
                .padding(.horizontal, 22)
                .padding(.vertical, 12)
                .background(isOn.wrappedValue ? Color.lsPrimary.opacity(0.28) : Color.lsCard)
                .clipShape(Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    // MARK: - Content branches

    @ViewBuilder
    private func eraSection(_ filtered: FilteredEra, vm: ArtistViewModel) -> some View {
        let era = filtered.era
        let isExpanded = vm.expandedEra == era.name
        let songs = filtered.sections.isEmpty
            ? filtered.songs
            : filtered.sections.flatMap(\.songs)

        VStack(alignment: .leading, spacing: 10) {
            Button {
                vm.expandedEra = isExpanded ? nil : era.name
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
                // `offset` in the id, not baseName — trackers emit several
                // distinct "???" songs per era, and ForEach would drop the
                // duplicates. Same reason EraRow.id carries an ordinal.
                ForEach(Array(songs.enumerated()), id: \.offset) { _, song in
                    TVSongRowView(song: song, eraName: era.name, eraArt: era.artUrl, artist: vm.artist)
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
    private func searchResults(_ vm: ArtistViewModel) -> some View {
        if vm.content.searchResults.isEmpty {
            ContentUnavailableView.search(text: vm.searchQuery)
                .padding(.top, 60)
        } else {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(vm.content.searchResults) { result in
                    TVVersionRowView(
                        version: result.version,
                        song: result.song,
                        eraName: result.era.name,
                        eraArt: result.era.artUrl,
                        artist: vm.artist
                    )
                }
            }
            .focusSection()
        }
    }

    @ViewBuilder
    private func miscSection(_ vm: ArtistViewModel) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Misc")
                .font(.title3.weight(.semibold))
                .padding(.horizontal, 60)
            ForEach(Array(vm.content.miscResults.enumerated()), id: \.offset) { _, entry in
                TVMiscRowView(entry: entry)
            }
        }
        .focusSection()
    }

    // MARK: - Refresh

    private func refresh() async {
        guard let url = artist.sourceUrl else { return }
        refreshing = true
        defer { refreshing = false }
        // Mirrors ArtistView.refresh() on iOS: forceRefresh skips the ETag
        // check so the backend actually re-parses, and the result is re-cached
        // — the tvOS version previously deleted the cache entry and never
        // wrote a new one, so every open after one refresh re-downloaded and
        // re-decoded the full multi-MB payload instead of replaying a 304.
        do {
            let result = try await APIClient.shared.parseSheet(
                url: url, artistName: artist.name, forceRefresh: true
            )
            if let etag = result.etag {
                await CacheService.shared.cacheTracker(url: url, data: result.rawData, etag: etag)
            }
            recents.saveTracker(artist: result.artist)
            vm = await ArtistViewModel.make(artist: result.artist)
        } catch {
            // Keep showing the current data; the Refresh button just re-enables.
        }
    }
}
