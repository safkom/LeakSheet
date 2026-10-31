import AVKit
import SwiftUI

extension NowPlayingView {
    @ViewBuilder
    var trackInfo: some View {
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
                    .foregroundStyle(Color.lsError)
                    .multilineTextAlignment(.center)
                if player.currentTrack != nil {
                    Button("Try Again") { player.retryCurrent() }
                    .font(.caption.weight(.semibold))
                    .buttonStyle(.glass)
                }
            }
        }
        .padding(.horizontal, 24)
    }

    @ViewBuilder
    var progressBar: some View {
        // Progress bar
        VStack(spacing: 4) {
            ScrubberSlider(tint: readableAccent ?? Color.lsAccent)

            HStack {
                PlaybackElapsedText()
                Spacer()
                Text(
                    player.duration > 0
                        ? Format.time(player.duration)
                        : (player.currentTrack?.trackLength ?? "--:--")
                )
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 32)
    }

    @ViewBuilder
    var transportControls: some View {
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
                    // .tint below applies to the whole button subtree, so an untinted indicator would
                    // draw in the era colour on a glass button filled with it. Same as the Image branch.
                    ProgressView()
                        .controlSize(.regular)
                        .tint(Color.preferredText(on: accentColor ?? Color.lsAccent, in: colorScheme))
                        .frame(width: 56, height: 56)
                } else {
                    Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(Color.preferredText(
                            on: accentColor ?? Color.lsAccent,
                            in: colorScheme
                        ))
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
    }

    @ViewBuilder
    var secondaryControls: some View {
        // Secondary controls row. Every child is incompressible, so tight spacing plus
        // horizontal padding keeps it inside a non-Max iPhone's width.
        HStack(spacing: 16) {
            // Queue
            Button {
                #if os(macOS)
                MacUIState.shared.inspectorTab = .queue
                MacUIState.shared.showInspector = true
                openWindow(id: "main")
                #else
                showQueue = true
                #endif
            } label: {
                Image(systemName: "list.bullet")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.glass)
            .accessibilityLabel("Queue")

            // Favourite
            if let track = player.currentTrack {
                let isFav = favourites.isFavouritedByVersion(
                    track,
                    artistSlug: player.artistSlug,
                    eraName: player.eraName
                )
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
                        .frame(width: 44, height: 44)
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
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.glass)
            .accessibilityLabel("Track details")
        }
    }

    @ToolbarContentBuilder
    var overflowMenu: some ToolbarContent {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        if let track = player.currentTrack {
                            Button {
                                player.addToQueue(
                                    track,
                                    artistName: player.artistName,
                                    eraName: player.eraName,
                                    artUrl: player.artUrl,
                                    artistSlug: player.artistSlug
                                )
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
                                    favourites.isFavouritedByVersion(
                                        track,
                                        artistSlug: player.artistSlug,
                                        eraName: player.eraName
                                    ) ? "Unfavourite" : "Favourite",
                                    systemImage: favourites.isFavouritedByVersion(
                                        track,
                                        artistSlug: player.artistSlug,
                                        eraName: player.eraName
                                    ) ? "heart.fill" : "heart"
                                )
                            }
                        }
                        if let link = player.currentTrack?.links?.first {
                            Button {
                                Pasteboard.copy(link)
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

    @ViewBuilder
    var artworkView: some View {
        if player.hasVideo, let avPlayer = player.avPlayer {
            // Video renders in place of artwork — see DECISIONS.md::NowPlayingView.swift::video-in-artwork-slot
            VideoSurfaceView(player: avPlayer)
                .aspectRatio(player.videoAspectRatio ?? 16.0 / 9.0, contentMode: .fit)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 16)
                .overlay(alignment: .topTrailing) {
                    Image(systemName: "arrow.up.left.and.arrow.down.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.white)
                        .padding(6)
                        .background(.ultraThinMaterial, in: Circle())
                        .padding(24)
                }
                .contentShape(Rectangle())
                .onTapGesture { showFullScreenVideo = true }
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel("Play video full screen")
                .background(
                    NativeFullScreenVideoPresenter(
                        player: avPlayer, isPresented: $showFullScreenVideo
                    )
                )
        } else if !player.artUrl.isEmpty {
            // 1600, as the lock-screen artwork loads, so both share one download and cache
            // entry; width matches maxPixelSize, as at every other call site.
            CachedImage(url: APIClient.shared.imageProxyURL(for: player.artUrl, width: 1600), maxPixelSize: 1600) {
                artPlaceholder
            }
            .modifier(ArtworkSquare())
        } else {
            artPlaceholder
                .modifier(ArtworkSquare())
        }
    }

    private var artPlaceholder: some View {
        ArtworkPlaceholder(cornerRadius: 0)
            .font(.system(size: 48))
    }
}
