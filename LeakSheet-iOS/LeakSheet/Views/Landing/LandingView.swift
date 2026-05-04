import SwiftUI

/// Landing screen — URL input, recent trackers, discovery.
struct LandingView: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(RecentTrackersManager.self) private var recents

    @State private var url: String = ""
    @State private var loading = false
    @State private var error: String?

    var onArtistLoaded: (Artist) -> Void
    var onBrowseTapped: () -> Void = {}
    @Binding var pendingBrowseUrl: String?

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
        .onChange(of: pendingBrowseUrl) { _, newValue in
            guard let pickedUrl = newValue else { return }
            url = pickedUrl
            pendingBrowseUrl = nil
            Task { await handleParse(pickedUrl) }
        }
    }

    private func handleParse(_ urlString: String) async {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        withAnimation { error = nil }
        loading = true
        defer { loading = false }

        do {
            let result = try await APIClient.shared.parseSheet(url: trimmed)
            recents.saveTracker(artist: result.artist)
            onArtistLoaded(result.artist)
        } catch let apiError as APIError {
            switch apiError {
            case .notModified:
                break
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
