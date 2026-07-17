import SwiftUI

/// Full-screen now-playing view with artwork, progress, and controls.
struct NowPlayingView: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites
    @Environment(\.dismiss) private var dismiss

    @State private var accentColor: Color?
    @State private var showQueue = false
    @State private var showDescription: DescriptionSheet.Payload?

    /// Era accent brightened until it reads against the actual backdrop at the
    /// controls' position — the gradient there is roughly the accent fading
    /// well into the black background, so very dark accents (navy, deep green)
    /// would otherwise render illegible tints.
    private var readableAccent: Color? {
        guard let accent = accentColor else { return nil }
        let backdrop = accent.blended(with: .lsBackground, fraction: 0.7)
        return accent.ensureReadable(against: backdrop)
    }

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
                    .tint(readableAccent ?? Color.lsAccent)

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
                                .foregroundStyle(Color.preferredText(on: accentColor ?? Color.lsAccent))
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
                            .foregroundStyle(player.originalQuality ? (readableAccent ?? Color.lsAccent) : .secondary)
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
                        let isFav = favourites.isFavouritedByVersion(track, artistSlug: player.artistSlug, eraName: player.eraName)
                        Button {
                            favourites.toggleFromVersion(
                                version: track,
                                artistSlug: player.artistSlug,
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
                                artistSlug: player.artistSlug,
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
                                player.addToQueue(track, artistName: player.artistName, eraName: player.eraName, artUrl: player.artUrl, artistSlug: player.artistSlug)
                                Haptics.light()
                            } label: {
                                Label("Add to Queue", systemImage: "text.append")
                            }
                            Button {
                                favourites.toggleFromVersion(
                                    version: track,
                                    artistSlug: player.artistSlug,
                                    artistName: player.artistName,
                                    sourceUrl: nil,
                                    eraName: player.eraName,
                                    eraArt: player.artUrl.isEmpty ? nil : player.artUrl
                                )
                                Haptics.light()
                            } label: {
                                Label(
                                    favourites.isFavouritedByVersion(track, artistSlug: player.artistSlug, eraName: player.eraName) ? "Unfavourite" : "Favourite",
                                    systemImage: favourites.isFavouritedByVersion(track, artistSlug: player.artistSlug, eraName: player.eraName) ? "heart.fill" : "heart"
                                )
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
                      let url = APIClient.shared.imageProxyURL(for: player.artUrl, width: 128) else {
                    accentColor = nil
                    return
                }
                accentColor = await EraColorExtractor.shared.extractColor(from: url, cacheKey: player.artUrl)
            }
        }
    }

    @ViewBuilder
    private var artworkView: some View {
        if player.hasVideo, let avPlayer = player.avPlayer {
            // Video items (e.g. an .mp4 behind an opaque pillows id) render
            // their picture in place of the artwork, driven by the same
            // player as the audio path.
            VideoSurfaceView(player: avPlayer)
        } else if !player.artUrl.isEmpty {
            CachedImage(url: APIClient.shared.imageProxyURL(for: player.artUrl, width: 1600)) {
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
