import AVKit
import SwiftUI

/// Full-screen player. Video uses AVKit's SwiftUI `VideoPlayer` against the
/// same shared AVPlayer the audio path drives, so there is no second player to
/// keep in sync and no UIKit bridge to maintain.
struct TVNowPlayingView: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss

    @State private var showQueue = false

    var body: some View {
        VStack(spacing: 36) {
            if player.hasVideo, let avPlayer = player.avPlayer {
                VideoPlayer(player: avPlayer)
                    .aspectRatio(player.videoAspectRatio ?? 16.0 / 9.0, contentMode: .fit)
                    .frame(maxHeight: 620)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
            } else {
                artwork
            }

            VStack(spacing: 10) {
                Text(player.currentTrack?.name ?? "Nothing playing")
                    .font(.largeTitle.bold())
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                Text(player.eraName.isEmpty
                     ? player.artistName
                     : "\(player.artistName) — \(player.eraName)")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }

            progress

            HStack(spacing: 24) {
                Button { player.playPrevious() } label: {
                    Image(systemName: "backward.fill")
                }
                Button { player.togglePlay() } label: {
                    Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                }
                Button { player.playNext() } label: {
                    Image(systemName: "forward.fill")
                }
                Button { showQueue = true } label: {
                    Label("Queue (\(player.queue.count))", systemImage: "list.bullet")
                }
            }
            .focusSection()

            if let error = player.error.isEmpty ? nil : player.error {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(Color.lsError)
            }
        }
        .padding(60)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.lsBackground)
        // The remote's dedicated play/pause button already reaches
        // MPRemoteCommandCenter; this covers the in-app case while focused.
        .onPlayPauseCommand { player.togglePlay() }
        .onExitCommand { dismiss() }
        .sheet(isPresented: $showQueue) { TVQueueView() }
    }

    @ViewBuilder
    private var artwork: some View {
        Group {
            if !player.artUrl.isEmpty,
               let url = APIClient.shared.imageProxyURL(for: player.artUrl, width: 1280) {
                CachedImage(url: url, maxPixelSize: 1280) {
                    ArtworkPlaceholder(cornerRadius: 20)
                }
                .aspectRatio(contentMode: .fill)
            } else {
                ArtworkPlaceholder(cornerRadius: 20)
            }
        }
        .frame(width: 480, height: 480)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private var progress: some View {
        VStack(spacing: 8) {
            ProgressView(
                value: min(player.currentTime, player.duration),
                total: max(player.duration, 1)
            )
            .frame(maxWidth: 900)
            HStack {
                Text(Format.time(player.currentTime))
                Spacer()
                Text(Format.time(player.duration))
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
            .frame(maxWidth: 900)
        }
    }
}
