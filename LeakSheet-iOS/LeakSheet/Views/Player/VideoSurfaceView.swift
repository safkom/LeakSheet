import AVFoundation
import SwiftUI

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
