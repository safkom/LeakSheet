import SwiftUI

/// Full-screen now-playing view with artwork, progress, and controls.
struct NowPlayingView: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites
    @Environment(\.dismiss) private var dismiss

    @State private var accentColor: Color?
    @State private var showQueue = false
    @State private var showDescription: DescriptionSheet.Payload?

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                // Artwork
                artworkView
                    .frame(width: 280, height: 280)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                    .shadow(color: (accentColor ?? .black).opacity(0.4), radius: 20, y: 10)

                // Track info
                VStack(spacing: 4) {
                    Text(player.currentTrack?.name ?? "Not Playing")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)

                    Text(player.eraName.isEmpty ? player.artistName : "\(player.artistName) — \(player.eraName)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)

                    if !player.error.isEmpty {
                        Text(player.error)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
                .padding(.horizontal, 24)

                // Progress bar
                VStack(spacing: 4) {
                    Slider(
                        value: Binding(
                            get: { player.displayTime },
                            set: { player.seekValue = $0 }
                        ),
                        in: 0...(player.duration > 0 ? player.duration : 1),
                        onEditingChanged: { editing in
                            player.seeking = editing
                            if !editing {
                                player.seekTo(player.seekValue)
                            }
                        }
                    )
                    .tint(accentColor ?? Color.lsAccent)

                    HStack {
                        Text(PlayerViewModel.formatTime(player.displayTime))
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(player.duration > 0 ? PlayerViewModel.formatTime(player.duration) : (player.currentTrack?.trackLength ?? "--:--"))
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 32)

                // Transport controls
                HStack(spacing: 40) {
                    Button {
                        player.playPrevious()
                    } label: {
                        Image(systemName: "backward.fill")
                            .font(.title2)
                            .foregroundStyle(.primary)
                            .frame(width: 44, height: 44)
                    }
                    .buttonStyle(.glass)
                    .accessibilityLabel("Previous track")

                    Button {
                        player.togglePlay()
                    } label: {
                        if player.loading {
                            ProgressView()
                                .controlSize(.regular)
                                .frame(width: 56, height: 56)
                        } else {
                            Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                                .font(.title2.weight(.semibold))
                                .foregroundStyle(.white)
                                .frame(width: 56, height: 56)
                                .contentTransition(.symbolEffect(.replace))
                        }
                    }
                    .buttonStyle(.glass)
                    .tint(accentColor ?? Color.lsAccent)
                    .accessibilityLabel(player.isPlaying ? "Pause" : "Play")

                    Button {
                        player.playNext()
                    } label: {
                        Image(systemName: "forward.fill")
                            .font(.title2)
                            .foregroundStyle(.primary)
                            .frame(width: 44, height: 44)
                    }
                    .buttonStyle(.glass)
                    .accessibilityLabel("Next track")
                }

                // Secondary controls row
                HStack(spacing: 28) {
                    // Quality toggle
                    if player.currentTrack != nil {
                        Button {
                            if player.originalQuality {
                                player.playCompressedStream()
                            } else {
                                player.playOriginalQuality()
                            }
                        } label: {
                            Label(
                                player.originalQuality ? "Original" : "Stream",
                                systemImage: player.originalQuality ? "waveform" : "antenna.radiowaves.left.and.right"
                            )
                            .font(.caption.weight(.medium))
                            .foregroundStyle(player.originalQuality ? (accentColor ?? Color.lsAccent) : .secondary)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                        }
                        .buttonStyle(.glass)
                    }

                    // Queue
                    Button {
                        showQueue = true
                    } label: {
                        Image(systemName: "list.bullet")
                            .font(.body)
                            .foregroundStyle(.secondary)
                            .frame(width: 36, height: 36)
                    }
                    .buttonStyle(.glass)
                    .accessibilityLabel("Queue")

                    // Favourite
                    if let track = player.currentTrack {
                        let isFav = favourites.entries.contains { $0.primaryVersionName == track.name }
                        Button {
                            favourites.toggleFromVersion(
                                version: track,
                                artistSlug: player.artistName.slugified,
                                artistName: player.artistName,
                                sourceUrl: nil,
                                eraName: player.eraName,
                                eraArt: player.artUrl.isEmpty ? nil : player.artUrl
                            )
                            Haptics.light()
                        } label: {
                            Image(systemName: isFav ? "heart.fill" : "heart")
                                .font(.body)
                                .foregroundStyle(isFav ? Color.lsFavourite : .secondary)
                                .frame(width: 36, height: 36)
                        }
                        .buttonStyle(.glass)
                        .accessibilityLabel(isFav ? "Remove from favourites" : "Add to favourites")
                    }

                    // Info
                    Button {
                        if let track = player.currentTrack {
                            showDescription = DescriptionSheet.Payload(
                                song: nil, version: track,
                                artistName: player.artistName,
                                artistSlug: player.artistName.slugified,
                                eraName: player.eraName,
                                eraArt: player.artUrl.isEmpty ? nil : player.artUrl
                            )
                        }
                    } label: {
                        Image(systemName: "info.circle")
                            .font(.body)
                            .foregroundStyle(.secondary)
                            .frame(width: 36, height: 36)
                    }
                    .buttonStyle(.glass)
                    .accessibilityLabel("Track details")
                }

                Spacer()
            }
            .background(
                ZStack {
                    Color.lsBackground
                    if let accent = accentColor {
                        LinearGradient(
                            colors: [
                                accent.opacity(0.85),
                                accent.opacity(0.45),
                                Color.lsBackground
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                        .ignoresSafeArea()
                    }
                }
                .ignoresSafeArea()
            )
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "chevron.down")
                            .font(.headline)
                    }
                    .accessibilityLabel("Close now playing")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        if let track = player.currentTrack {
                            Button {
                                player.addToQueue(track, artistName: player.artistName, eraName: player.eraName, artUrl: player.artUrl)
                                Haptics.light()
                            } label: {
                                Label("Add to Queue", systemImage: "text.append")
                            }
                            Button {
                                favourites.toggleFromVersion(
                                    version: track,
                                    artistSlug: player.artistName.slugified,
                                    artistName: player.artistName,
                                    sourceUrl: nil,
                                    eraName: player.eraName,
                                    eraArt: player.artUrl.isEmpty ? nil : player.artUrl
                                )
                                Haptics.light()
                            } label: {
                                Label("Favourite", systemImage: "heart")
                            }
                        }
                        if let link = player.currentTrack?.links?.first {
                            Button {
                                UIPasteboard.general.string = link
                            } label: {
                                Label("Copy Link", systemImage: "doc.on.doc")
                            }
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .accessibilityLabel("More options")
                }
            }
            .sheet(isPresented: $showQueue) {
                QueueSheet()
                    .environment(PlayerViewModel.shared)
            }
            .sheet(item: $showDescription) { payload in
                SongDescriptionSheet(payload: payload)
                    .environment(FavouritesManager.shared)
                    .environment(PlayerViewModel.shared)
            }
            .task(id: player.artUrl) {
                guard !player.artUrl.isEmpty,
                      let url = APIClient.shared.imageProxyURL(for: player.artUrl) else {
                    accentColor = nil
                    return
                }
                accentColor = await EraColorExtractor.shared.extractColor(from: url, eraName: player.eraName)
            }
        }
    }

    @ViewBuilder
    private var artworkView: some View {
        if !player.artUrl.isEmpty {
            CachedImage(url: APIClient.shared.imageProxyURL(for: player.artUrl)) {
                artPlaceholder
            }
        } else {
            artPlaceholder
        }
    }

    private var artPlaceholder: some View {
        Image(systemName: "music.note")
            .font(.system(size: 48))
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.lsCard)
    }
}
