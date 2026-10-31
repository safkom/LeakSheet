import SwiftUI
#if os(iOS)
import AVKit
#endif

/// Full-screen now-playing view with artwork, progress, and controls.
struct NowPlayingView: View {
    @Environment(PlayerViewModel.self) var player
    @Environment(FavouritesManager.self) var favourites
    /// The open tracker's view model, forwarded from the mini player. Lets the
    /// description sheet below recover the full song (and its sibling
    /// versions) from the bare SongVersion the player holds.
    @Environment(ArtistViewModel.self) var artistVM: ArtistViewModel?
    @Environment(\.dismiss) var dismiss
    #if os(macOS)
    /// The queue is the main window's inspector on the Mac; this button has to
    /// bring that window forward, not open a sheet over this one.
    @Environment(\.openWindow) var openWindow
    #endif

    /// Contrast is judged against the appearance actually on screen (the Mac renders
    /// in the system appearance): see DECISIONS.md::DesignTokens.swift::scheme-parameter.
    @Environment(\.colorScheme) var colorScheme
    @Environment(\.dynamicTypeSize) var dynamicTypeSize

    @State var accentColor: Color?
    #if !os(macOS)
    /// iOS only — on the Mac the queue is the main window's inspector (⌥⌘Q),
    /// not a sheet stacked on top of this one.
    @State var showQueue = false
    #endif
    @State var showDescription: DescriptionSheet.Payload?
    @State var showFullScreenVideo = false

    /// Era accent brightened until it reads against the actual backdrop at the
    /// controls, where the gradient fades into the background.
    var readableAccent: Color? {
        guard let accent = accentColor else { return nil }
        let backdrop = accent.blended(with: .lsBackground, fraction: 0.7, in: colorScheme)
        return accent.ensureReadable(against: backdrop, in: colorScheme)
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
                    ToolbarItem(placement: .primaryAction) {
                        AirPlayButton()
                            .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                            .accessibilityLabel("AirPlay")
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

    @ViewBuilder
    private var content: some View {
        // Fixed at standard text sizes: the artwork gives way to the controls. Only
        // accessibility sizes, where the text alone can outgrow the screen, scroll.
        if dynamicTypeSize.isAccessibilitySize {
            ScrollView { controls }
        } else {
            controls
        }
    }

    private var controls: some View {
            VStack(spacing: 24) {
                Spacer()

                // Artwork — square for album art; videos break out of the
                // 1:1 frame and render full-width at their natural aspect
                // ratio (no letterboxing inside the square).
                artworkView
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                    .shadow(color: (accentColor ?? .black).opacity(0.4), radius: 20, y: 10)

                trackInfo
                progressBar
                transportControls
                secondaryControls

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

}

/// Square artwork frame, sized to the space it gets: fills the width up to a cap
/// and, being aspect-fit, gives way vertically when the controls need room.
struct ArtworkSquare: ViewModifier {
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
        // A clear square the artwork fills, rather than aspect-fitting the
        // artwork itself: covers are not always square, and the frame is.
        Color.clear
            .aspectRatio(1, contentMode: .fit)
            .overlay { content }
            .clipped()
            .frame(maxWidth: 340)
            .padding(.horizontal, 32)
        #endif
    }
}

#if os(iOS)
/// The system route picker (AirPlay, Bluetooth, HomePod).
private struct AirPlayButton: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView {
        let view = AVRoutePickerView()
        view.prioritizesVideoDevices = false
        return view
    }

    func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
}
#endif
