import SwiftUI

/// Lyrics for the playing track: synced lines follow playback (tap to seek), plain text otherwise.
struct LyricsView: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss

    private enum Phase { case loading, loaded(Lyrics), failed }
    @State private var phase: Phase = .loading
    @State private var safariItem: SafariItem?

    private var title: String { player.currentTrack.map { LyricsParsing.searchTitle($0.name) } ?? "" }

    var body: some View {
        NavigationStack {
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.lsBackground)
                .navigationTitle(title)
                #if os(iOS)
                .toolbarTitleDisplayMode(.inline)
                #endif
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                    ToolbarItem(placement: .primaryAction) { geniusButton }
                }
        }
        .webSheet(item: $safariItem)
        .task(id: "\(player.artistName)|\(title)") { await load() }
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loading:
            ProgressView()
        case .failed:
            ContentUnavailableView {
                Label("Couldn't load lyrics", systemImage: "wifi.exclamationmark")
            } actions: {
                Button("Retry") { Task { await load() } }
            }
        case .loaded(let lyrics) where lyrics.isEmpty:
            ContentUnavailableView("No lyrics found", systemImage: "text.quote",
                description: Text("Unreleased songs often have none. Genius may have the page."))
        case .loaded(let lyrics) where !lyrics.synced.isEmpty:
            synced(lyrics)
        case .loaded(let lyrics):
            ScrollView {
                Text(lyrics.plain ?? "")
                    .font(.title3)
                    .padding(20)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
        }
    }

    private func synced(_ lyrics: Lyrics) -> some View {
        let current = lyrics.currentIndex(at: player.currentTime)
        return ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(Array(lyrics.synced.enumerated()), id: \.offset) { index, line in
                        Button { player.seekTo(line.time) } label: {
                            Text(line.text.isEmpty ? "♪" : line.text)
                                .font(.title2.weight(.bold))
                                .foregroundStyle(index == current ? Color.primary : Color.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                        .id(index)
                    }
                }
                .padding(20)
            }
            .onChange(of: current) { _, index in
                guard let index else { return }
                withAnimation { proxy.scrollTo(index, anchor: .center) }
            }
        }
    }

    private var geniusButton: some View {
        Button {
            var components = URLComponents(string: "https://genius.com/search")
            components?.queryItems = [URLQueryItem(name: "q", value: "\(player.artistName) \(title)")]
            safariItem = components?.url.map(SafariItem.init)
        } label: {
            Label("Genius", systemImage: "magnifyingglass")
        }
        .accessibilityHint("Searches Genius for this song")
    }

    private func load() async {
        guard !title.isEmpty else { return }
        phase = .loading
        let duration = player.duration > 0 ? player.duration : nil
        if let lyrics = await LyricsService.shared.lyrics(artist: player.artistName, title: title, duration: duration) {
            phase = .loaded(lyrics)
        } else {
            phase = .failed
        }
    }
}
