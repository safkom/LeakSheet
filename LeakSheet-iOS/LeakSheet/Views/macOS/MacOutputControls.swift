#if os(macOS)
import AVKit
import SwiftUI

/// Volume and output device for the Mac player bar: the keyboard's volume keys set the
/// system level, and this one sets the player's own, as Music does.
struct MacOutputControls: View {
    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        @Bindable var player = player
        HStack(spacing: 6) {
            Image(systemName: player.volume == 0 ? "speaker.slash.fill" : "speaker.fill")
                .font(.caption)
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Slider(value: $player.volume, in: 0...1)
                .frame(width: 90)
                .controlSize(.small)
                .accessibilityLabel("Volume")
            RoutePicker()
                .frame(width: 22, height: 22)
                .help("Output device")
                .accessibilityLabel("Output device")
        }
    }
}

/// The system route picker (AirPlay and other outputs).
private struct RoutePicker: NSViewRepresentable {
    func makeNSView(context: Context) -> AVRoutePickerView {
        let view = AVRoutePickerView()
        view.isRoutePickerButtonBordered = false
        return view
    }

    func updateNSView(_ nsView: AVRoutePickerView, context: Context) {}
}
#endif
