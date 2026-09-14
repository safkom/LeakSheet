import SwiftUI

/// The seek slider shared by the mini player and Now Playing.
///
/// A view of its own so the ~10 Hz time updates invalidate only this row.
/// Inline, each parent read `player.displayTime` in its own body, so every tick
/// re-ran the whole mini player and the whole Now Playing screen — the latter
/// including the WCAG contrast search for its era tint, twice per pass.
struct ScrubberSlider: View {
    @Environment(PlayerViewModel.self) private var player
    var tint: Color = .lsAccent

    /// How far one VoiceOver swipe moves the playhead.
    private static let accessibilityStep: TimeInterval = 15

    var body: some View {
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
        .tint(tint)
        // Unlabelled, VoiceOver read the raw TimeInterval — "142.0".
        .accessibilityLabel("Playback position")
        .accessibilityValue("\(Self.spoken(player.displayTime)) of \(Self.spoken(player.duration))")
        // Slider's built-in adjustment only writes the binding, which sets the
        // scrub target without ever calling onEditingChanged — so a VoiceOver
        // swipe moved nothing. Seek directly instead.
        .accessibilityAdjustableAction { direction in
            // No known length yet (loading, or a live stream): clamping to a
            // duration of 0 sent every swipe back to the start.
            guard player.duration > 0 else { return }
            let step = direction == .increment ? Self.accessibilityStep : -Self.accessibilityStep
            player.seekTo(min(max(player.currentTime + step, 0), player.duration))
        }
    }

    /// "2 minutes, 22 seconds" — a clock string like "2:22" reads ambiguously.
    private static func spoken(_ seconds: TimeInterval) -> String {
        guard seconds.isFinite, seconds > 0 else { return "0 seconds" }
        return Duration.seconds(seconds.rounded())
            .formatted(.units(allowed: [.hours, .minutes, .seconds], width: .wide))
    }
}

/// Elapsed time, in its own view for the same reason as `ScrubberSlider`.
struct PlaybackElapsedText: View {
    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        Text(Format.time(player.displayTime))
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.secondary)
            // The slider already speaks the position; repeating it per tick
            // would only interrupt.
            .accessibilityHidden(true)
    }
}
