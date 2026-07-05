import SwiftUI

/// A tracker picked from the browse list — carries the curated artist name so
/// the API doesn't have to infer it from the sheet title (which may be a joke
/// name like "Creator, The Tyler Tracker").
struct PendingBrowse: Equatable {
    let url: String
    let name: String?
}

/// Landing screen — URL input, recent trackers, discovery.
struct LandingView: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(RecentTrackersManager.self) private var recents

    @State private var url: String = ""
    @State private var loading = false
    @State private var error: String?

    var onArtistLoaded: (Artist) -> Void
    var onBrowseTapped: () -> Void = {}
    @Binding var pendingBrowse: PendingBrowse?

    var body: some View {
        ScrollView {
            VStack(spacing: 32) {
                // Header
                VStack(spacing: 8) {
                    Text("LeakSheet")
                        .font(.largeTitle.bold())
                        .foregroundStyle(.white)
                    Text("Music tracker parser")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding(.top, 48)

                // URL Input
                TrackerInputView(url: $url, loading: loading) {
                    await handleParse(url)
                }
                .padding(.horizontal, 20)

                // Browse artists button
                Button {
                    onBrowseTapped()
                } label: {
                    Label("Browse Artists", systemImage: "music.note.list")
                        .font(.subheadline.weight(.medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .foregroundStyle(.primary)
                        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 20)

                // Error
                if let error {
                    Text(error)
                        .font(.callout)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 20)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }

                // Recent trackers
                if !recents.trackers.isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("Recent")
                                .font(.headline)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Button("Clear") {
                                recents.clearAll()
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 20)

                        LazyVStack(spacing: 8) {
                            ForEach(recents.trackers) { entry in
                                RecentTrackerCardView(entry: entry) {
                                    url = entry.sourceUrl
                                    Task { await handleParse(entry.sourceUrl) }
                                }
                                .padding(.horizontal, 20)
                            }
                        }
                    }
                }

                Spacer(minLength: 100)
            }
        }
        .background(Color.lsBackground)
        .scrollDismissesKeyboard(.interactively)
        .onChange(of: pendingBrowse) { _, newValue in
            guard let picked = newValue else { return }
            url = picked.url
            pendingBrowse = nil
            Task { await handleParse(picked.url, artistName: picked.name) }
        }
    }

    private func handleParse(_ urlString: String, artistName: String? = nil) async {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        withAnimation { error = nil }
        loading = true
        defer { loading = false }

        // Conditional request: send the cached ETag so an unchanged tracker
        // comes back as a bodyless 304 and we reopen the local copy instead
        // of re-downloading and re-decoding the full multi-MB payload.
        let cachedEtag = await CacheService.shared.getCachedEtag(for: trimmed)

        do {
            let result = try await APIClient.shared.parseSheet(url: trimmed, artistName: artistName, cachedEtag: cachedEtag)
            if let etag = result.etag {
                await CacheService.shared.cacheTracker(
                    url: trimmed,
                    artist: result.artist,
                    etag: etag,
                    totalSongs: result.artist.computedTotalSongs,
                    totalVersions: result.artist.computedTotalVersions
                )
            }
            recents.saveTracker(artist: result.artist)
            onArtistLoaded(result.artist)
        } catch let apiError as APIError {
            switch apiError {
            case .notModified:
                if let cachedArtist = await CacheService.shared.getCachedArtist(for: trimmed) {
                    recents.saveTracker(artist: cachedArtist)
                    onArtistLoaded(cachedArtist)
                } else {
                    // ETag matched but local copy is gone — refetch unconditionally.
                    await CacheService.shared.removeTracker(for: trimmed)
                    do {
                        let result = try await APIClient.shared.parseSheet(url: trimmed, artistName: artistName)
                        recents.saveTracker(artist: result.artist)
                        onArtistLoaded(result.artist)
                    } catch {
                        withAnimation { self.error = "Failed to load tracker" }
                    }
                }
            case .httpError(_, let msg):
                withAnimation { error = msg }
            case .decodingError:
                withAnimation { error = "Failed to parse tracker data" }
            case .invalidURL:
                withAnimation { error = "Invalid URL" }
            }
        } catch {
            withAnimation { self.error = error.localizedDescription }
        }
    }
}
