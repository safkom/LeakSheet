import SwiftUI

/// Full-screen now-playing view with artwork, progress, and controls.
struct NowPlayingView: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites
    /// The open tracker's view model, forwarded from the mini player. Lets the
    /// description sheet below recover the full song (and its sibling
    /// versions) from the bare SongVersion the player holds.
    @Environment(ArtistViewModel.self) private var artistVM: ArtistViewModel?
    @Environment(\.dismiss) private var dismiss
    #if os(macOS)
    /// The queue is the main window's inspector on the Mac; this button has to
    /// bring that window forward, not open a sheet over this one.
    @Environment(\.openWindow) private var openWindow
    #endif

    @State private var accentColor: Color?
    #if !os(macOS)
    /// iOS only — on the Mac the queue is the main window's inspector (⌥⌘Q),
    /// not a sheet stacked on top of this one.
    @State private var showQueue = false
    #endif
    @State private var showDescription: DescriptionSheet.Payload?
    @State private var showFullScreenVideo = false

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
        #if os(macOS)
        // No NavigationStack: this is a window, and its titlebar already
        // supplies the chrome an inline nav bar would duplicate.
        content
            .toolbar { overflowMenu }
        #else
        NavigationStack {
            content
                .toolbarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "chevron.down")
                                .font(.headline)
                        }
                        .accessibilityLabel("Close now playing")
                    }
                    overflowMenu
                }
                .sheet(isPresented: $showQueue) {
                    QueueSheet()
                        .environment(PlayerViewModel.shared)
                }
        }
        #endif
    }

    private var content: some View {
            VStack(spacing: 24) {
                Spacer()

                // Artwork — square for album art; videos break out of the
                // 1:1 frame and render full-width at their natural aspect
                // ratio (no letterboxing inside the square).
                artworkView
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
                            .foregroundStyle(Color.lsError)
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
                        Text(Format.time(player.displayTime))
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(player.duration > 0 ? Format.time(player.duration) : (player.currentTrack?.trackLength ?? "--:--"))
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
                            // .tint below applies to the whole button subtree,
                            // so an untinted indicator drew in the era colour
                            // on a glass button filled with that same colour —
                            // invisible. Same treatment the Image branch uses.
                            ProgressView()
                                .controlSize(.regular)
                                .tint(Color.preferredText(on: accentColor ?? Color.lsAccent))
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

                // Secondary controls row.
                // Spacing reduced from 28 and horizontal padding added: every
                // child here is incompressible (a fixed-size label plus three
                // 44pt frames, each in a glass capsule), and unlike the track
                // info and progress rows this one had no padding at all — so
                // on a non-Max iPhone the row overflowed and the widest,
                // leftmost child (the quality button) ran off the left edge.
                HStack(spacing: 16) {
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
                            // lineLimit(1) still prevents the two-line wrap
                            // that DECISIONS.md::NowPlayingView.swift::original-label-width
                            // records, but without fixedSize — which turned
                            // that wrap into an off-screen overflow. The label
                            // may now truncate on the narrowest devices
                            // instead of pushing the row past the bezel.
                            .lineLimit(1)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                        }
                        .buttonStyle(.glass)
                    }

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
            .sheet(item: $showDescription) { payload in
                SongDescriptionSheet(payload: payload)
                    .environment(FavouritesManager.shared)
                    .environment(PlayerViewModel.shared)
                    .environment(artistVM)
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

    @ToolbarContentBuilder
    private var overflowMenu: some ToolbarContent {
                ToolbarItem(placement: .primaryAction) {
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
    private var artworkView: some View {
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
            CachedImage(url: APIClient.shared.imageProxyURL(for: player.artUrl, width: 1600)) {
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

/// Square artwork frame. Fixed on iPhone (one screen size class per device);
/// window-relative on the Mac, where the Now Playing window is resizable and a
/// hard 280pt square left the rest of it empty.
private struct ArtworkSquare: ViewModifier {
    func body(content: Content) -> some View {
        #if os(macOS)
        GeometryReader { proxy in
            let side = max(120, min(proxy.size.width - 48, proxy.size.height))
            content
                .frame(width: side, height: side)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .aspectRatio(1, contentMode: .fit)
        .layoutPriority(1)
        #else
        content.frame(width: 280, height: 280)
        #endif
    }
}
