import SwiftUI

/// Mini player bar shown at bottom of screen when a track is loaded.
struct MiniPlayerBar: View {
    @Environment(PlayerViewModel.self) private var player
    /// Forwarded to Now Playing so its description sheet can resolve the song
    /// behind the playing version. Nil when nothing relevant is loaded.
    @Environment(ArtistViewModel.self) private var artistVM: ArtistViewModel?
    #if !os(macOS)
    @State private var showNowPlaying = false
    #endif
    #if os(macOS)
    /// Now Playing is a real window on the Mac (⇧⌘0). Raising the same window
    /// on a click keeps one surface instead of a modal sheet duplicating it.
    @Environment(\.openWindow) private var openWindow
    #endif

    var body: some View {
        if let track = player.currentTrack {
            VStack(spacing: 0) {
                // Progress slider
                if player.duration > 0 {
                    @Bindable var player = player
                    Slider(
                        value: $player.scrubPosition,
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
                        #if os(macOS)
                        openWindow(id: "now-playing")
                        #else
                        showNowPlaying = true
                        #endif
                    } label: {
                        HStack(spacing: 10) {
                            // Art
                            if !player.artUrl.isEmpty {
                                CachedImage(url: APIClient.shared.imageProxyURL(for: player.artUrl, width: 128), maxPixelSize: 128) {
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
                                        Text(Format.time(player.displayTime))
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
                    HStack(spacing: Metrics.hitTarget / 2) {
                        // Hit targets follow Metrics: the 44pt HIG minimum on
                        // touch, roughly half that for a pointer.
                        Button {
                            player.playPrevious()
                        } label: {
                            Image(systemName: "backward.fill")
                                .font(.body)
                                .foregroundStyle(.primary)
                                .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Previous track")

                        // Spinner overlays the button rather than replacing it:
                        // swapping the Button out removed the tap target for
                        // the whole load, so pausing a slow stream was
                        // impossible until it started.
                        Button {
                            player.togglePlay()
                        } label: {
                            Image(systemName: player.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                                .font(.system(size: Metrics.hitTarget * 0.86))
                                .foregroundStyle(Color.lsAccent)
                                .opacity(player.loading ? 0 : 1)
                                .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                                .overlay {
                                    if player.loading {
                                        ProgressView()
                                            .controlSize(.regular)
                                            .tint(Color.lsAccent)
                                    }
                                }
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(player.isPlaying ? "Pause" : "Play")

                        Button {
                            player.playNext()
                        } label: {
                            Image(systemName: "forward.fill")
                                .font(.body)
                                .foregroundStyle(.primary)
                                .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                                .contentShape(Rectangle())
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
            #if os(macOS)
            // Publish the height so the inspector can clear it — see
            // MacUIState.playerBarHeight.
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                MacUIState.shared.playerBarHeight = height
            }
            #endif
            #if !os(macOS)
            .sheet(isPresented: $showNowPlaying) {
                NowPlayingView()
                    .environment(PlayerViewModel.shared)
                    .environment(FavouritesManager.shared)
                    .environment(artistVM)
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
            }
            #endif
        }
    }

    private var artPlaceholder: some View {
        ArtworkPlaceholder(cornerRadius: 6)
            .frame(width: 40, height: 40)
    }
}
