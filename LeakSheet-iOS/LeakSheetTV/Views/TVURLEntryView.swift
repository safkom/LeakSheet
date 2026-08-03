import SwiftUI

/// Paste-a-URL parity with the phone, via the tvOS on-screen keyboard.
/// There is deliberately no Paste button: UIPasteboard is unavailable on tvOS,
/// so it would be a dead control.
struct TVURLEntryView: View {
    @Environment(RecentTrackersManager.self) private var recents

    @State private var loader = TrackerLoader()
    @State private var path: [TVRoute] = []

    var body: some View {
        NavigationStack(path: $path) {
            VStack(spacing: 32) {
                VStack(spacing: 10) {
                    Text("Open a Tracker")
                        .font(.largeTitle.bold())
                    Text("Enter a tracker URL — a Google Sheet link, or a site like yetracker.net.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                TextField("https://…", text: $loader.url)
                    .textFieldStyle(.plain)
                    .autocorrectionDisabled()
                    .urlFieldTraits()
                    .frame(maxWidth: 900)
                    .onSubmit { Task { await open() } }

                if loader.loading {
                    HStack(spacing: 12) {
                        ProgressView()
                        Text(phaseLabel)
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Button("Open Tracker") { Task { await open() } }
                        .disabled(loader.url.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }

                if let error = loader.error {
                    Text(error)
                        .font(.callout)
                        .foregroundStyle(Color.lsError)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 900)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.lsBackground)
            .navigationTitle("Add URL")
            .navigationDestination(for: TVRoute.self) { $0.destination }
        }
    }

    /// The phone shows byte counts here; ten feet away that's unreadable, so
    /// tvOS shows the phase only.
    private var phaseLabel: String {
        switch loader.loadPhase {
        case .connecting, nil: "Contacting server…"
        case .downloading: "Downloading…"
        case .preparing: "Preparing…"
        }
    }

    private func open() async {
        // Same normalisation the phone applies to a hand-entered URL.
        let normalized = TrackerURLNormalizer.normalize(loader.url)
        if let artist = await loader.load(normalized, recents: recents) {
            path.append(.artist(artist))
        }
    }
}
