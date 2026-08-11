import AVFoundation
import AVKit
import SwiftUI

#if os(macOS)

/// macOS video surface. AVKit's SwiftUI `VideoPlayer` renders the same shared
/// AVPlayer and brings its own transport chrome and full-screen button, which
/// is the Mac convention — so the platform has no separate presenter.
/// See DECISIONS.md::VideoSurfaceView.swift::macos-videoplayer.
struct VideoSurfaceView: View {
    let player: AVPlayer?

    var body: some View {
        if let player {
            VideoPlayer(player: player)
        } else {
            Color.black
        }
    }
}

/// No-op on macOS — `VideoPlayer` owns its own full-screen affordance. Kept so
/// `NowPlayingView` needs no conditional at its call site.
struct NativeFullScreenVideoPresenter: View {
    let player: AVPlayer?
    @Binding var isPresented: Bool

    var body: some View { EmptyView() }
}

#else

/// AVPlayerLayer host bound to the engine's shared AVPlayer. Shown in place
/// of the Now Playing artwork when the current item carries a video track —
/// playback state, scrubbing, and remote controls stay unified because the
/// layer renders the same player the audio path drives. When the view goes
/// away (background, dismissal) the layer detaches and playback continues
/// audio-only.
struct VideoSurfaceView: UIViewRepresentable {
    let player: AVPlayer?

    final class PlayerLayerView: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }

    func makeUIView(context: Context) -> PlayerLayerView {
        let view = PlayerLayerView()
        view.playerLayer.videoGravity = .resizeAspect
        view.playerLayer.player = player
        view.backgroundColor = .black
        return view
    }

    func updateUIView(_ view: PlayerLayerView, context: Context) {
        view.playerLayer.player = player
    }
}

/// Presents the native AVPlayerViewController modally when `isPresented`
/// flips true — a true UIKit presentation, so the player shows its OWN
/// chrome (Done button, transport controls, AirPlay) with nothing custom
/// layered on top. Bound to the SAME AVPlayer the inline surface and audio
/// path drive; dismissing continues playback inline. Attach to any view via
/// `.background(...)` — it renders nothing itself.
struct NativeFullScreenVideoPresenter: UIViewControllerRepresentable {
    let player: AVPlayer?
    @Binding var isPresented: Bool

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIViewController(context: Context) -> UIViewController {
        UIViewController()
    }

    func updateUIViewController(_ host: UIViewController, context: Context) {
        if isPresented, context.coordinator.playerController == nil {
            let controller = DismissReportingPlayerViewController()
            controller.player = player
            controller.showsPlaybackControls = true
            controller.videoGravity = .resizeAspect
            controller.onDismiss = { [weak coordinator = context.coordinator] in
                coordinator?.playerController = nil
                isPresented = false
            }
            context.coordinator.playerController = controller
            host.present(controller, animated: true)
        } else if !isPresented, let controller = context.coordinator.playerController {
            context.coordinator.playerController = nil
            controller.presentingViewController?.dismiss(animated: true)
        }
    }

    final class Coordinator {
        var playerController: DismissReportingPlayerViewController?
    }

    /// The presenter's view branch disappears when the current track loses
    /// its video (e.g. autoplay advances to an audio-only song). Without
    /// this, an already-presented fullscreen player would be orphaned with
    /// no binding left to dismiss it.
    static func dismantleUIViewController(_ host: UIViewController, coordinator: Coordinator) {
        if let controller = coordinator.playerController {
            coordinator.playerController = nil
            controller.onDismiss = nil
            controller.presentingViewController?.dismiss(animated: true)
        }
    }
}

/// AVPlayerViewController that reports when its own Done button (or any
/// other dismissal) removed it, so the SwiftUI binding stays in sync.
final class DismissReportingPlayerViewController: AVPlayerViewController {
    var onDismiss: (() -> Void)?

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        if isBeingDismissed || presentingViewController == nil {
            onDismiss?()
        }
    }
}

#endif
