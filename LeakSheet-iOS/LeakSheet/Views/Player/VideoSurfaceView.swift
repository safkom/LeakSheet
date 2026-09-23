import AVFoundation
import AVKit
import SwiftUI

#if os(macOS)

/// macOS video surface. AVKit's SwiftUI `VideoPlayer` renders the same shared
/// AVPlayer with its own transport chrome and full-screen button, the Mac convention.
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

/// AVPlayerLayer host bound to the engine's shared AVPlayer, shown in place of the
/// Now Playing artwork for video. When the view goes away the layer detaches and
/// playback continues audio-only.
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

/// Presents the native AVPlayerViewController modally (its OWN chrome, nothing
/// layered on top) when `isPresented` flips true, bound to the same AVPlayer.
/// Attach via `.background(...)`; it renders nothing itself.
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

    /// The presenter's view branch disappears when the track loses its video (autoplay
    /// to an audio-only song); dismiss here so the fullscreen player isn't orphaned.
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
