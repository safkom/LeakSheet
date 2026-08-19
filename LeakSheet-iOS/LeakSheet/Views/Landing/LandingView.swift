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
    @Environment(RecentTrackersManager.self) private var recents

    @State private var loader = TrackerLoader()

    /// Async so the caller can finish preparing the artist screen (building
    /// its view model) while this screen's loading state is still up — one
    /// loading state per tracker, not two.
    var onArtistLoaded: (Artist) async -> Void
    var onBrowseTapped: () -> Void = {}
    @Binding var pendingBrowse: PendingBrowse?

    var body: some View {
        ScrollView {
            VStack(spacing: 32) {
                // Header
                VStack(spacing: 8) {
                    Text("LeakSheet")
                        .font(.largeTitle.bold())
                        .foregroundStyle(.primary)
                    Text("Music tracker parser")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding(.top, 48)

                // URL Input
                TrackerInputView(
                    url: $loader.url,
                    loading: loader.loading,
                    loadPhase: loader.loadPhase
                ) {
                    await handleParse(loader.url)
                }
                .padding(.horizontal, 20)

                // Explore trackers button
                Button {
                    onBrowseTapped()
                } label: {
                    Label("Explore Trackers", systemImage: "music.note.list")
                        .font(.subheadline.weight(.medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .foregroundStyle(.primary)
                        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 20)

                // Error
                if let error = loader.error {
                    Text(error)
                        .font(.callout)
                        .foregroundStyle(Color.lsError)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 20)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }

                // Recent trackers
                RecentTrackersListView { entry in
                    loader.url = entry.sourceUrl
                    Task { await handleParse(entry.sourceUrl) }
                }

                Spacer(minLength: 100)
            }
        }
        .background(Color.lsBackground)
        .scrollDismissesKeyboard(.interactively)
        .onChange(of: pendingBrowse) { _, newValue in
            guard let picked = newValue else { return }
            loader.url = picked.url
            pendingBrowse = nil
            Task { await handleParse(picked.url, artistName: picked.name) }
        }
    }

    private func handleParse(_ urlString: String, artistName: String? = nil) async {
        if let artist = await loader.load(urlString, artistName: artistName, recents: recents) {
            // Inside `preparing` so the progress row stays up through the
            // view-model build and the first-screenful art warm.
            await loader.preparing { await onArtistLoaded(artist) }
        }
    }
}
