import SwiftUI

/// Mini player bar shown at bottom of screen when a track is loaded.
struct MiniPlayerBar: View {
    @Environment(PlayerViewModel.self) private var player
    @State private var showNowPlaying = false

    var body: some View {
        if let track = player.currentTrack {
            VStack(spacing: 0) {
                // Progress slider
                if player.duration > 0 {
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
                    .tint(Color.lsAccent)
                    .frame(height: 16)
                    .padding(.horizontal, 16)
                    .padding(.top, 6)
                }

                HStack(spacing: 10) {
                    // Tappable area for now playing view
                    Button {
                        showNowPlaying = true
                    } label: {
                        HStack(spacing: 10) {
                            // Art
                            if !player.artUrl.isEmpty {
                                CachedImage(url: APIClient.shared.imageProxyURL(for: player.artUrl)) {
                                    artPlaceholder
                                }
                                .frame(width: 40, height: 40)
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                            } else {
                                artPlaceholder
                                    .frame(width: 40, height: 40)
                            }

                            // Track info
                            VStack(alignment: .leading, spacing: 2) {
                                Text(track.name)
                                    .font(.subheadline.weight(.medium))
                                    .foregroundStyle(.primary)
                                    .lineLimit(1)
                                HStack(spacing: 4) {
                                    Text(player.eraName.isEmpty ? player.artistName : "\(player.artistName) · \(player.eraName)")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                    if player.duration > 0 {
                                        Text(PlayerViewModel.formatTime(player.displayTime))
                                            .font(.caption2.monospacedDigit())
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    }
                    .buttonStyle(.plain)

                    Spacer()

                    // Transport controls
                    HStack(spacing: 20) {
                        Button {
                            player.playPrevious()
                        } label: {
                            Image(systemName: "backward.fill")
                                .font(.body)
                                .foregroundStyle(.primary)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Previous track")

                        if player.loading {
                            ProgressView()
                                .controlSize(.regular)
                                .frame(width: 38, height: 38)
                        } else {
                            Button {
                                player.togglePlay()
                            } label: {
                                Image(systemName: player.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                                    .font(.system(size: 38))
                                    .foregroundStyle(Color.lsAccent)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel(player.isPlaying ? "Pause" : "Play")
                        }

                        Button {
                            player.playNext()
                        } label: {
                            Image(systemName: "forward.fill")
                                .font(.body)
                                .foregroundStyle(.primary)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Next track")
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
            }
            .glassEffect(in: .rect(cornerRadius: 16))
            .padding(.horizontal, 12)
            .padding(.bottom, 4)
            .sheet(isPresented: $showNowPlaying) {
                NowPlayingView()
                    .environment(PlayerViewModel.shared)
                    .environment(FavouritesManager.shared)
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
            }
        }
    }

    private var artPlaceholder: some View {
        Image(systemName: "music.note")
            .foregroundStyle(.secondary)
            .frame(width: 40, height: 40)
            .background(Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}
