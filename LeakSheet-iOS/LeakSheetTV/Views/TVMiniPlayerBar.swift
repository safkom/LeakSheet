import SwiftUI

/// Bottom now-playing strip, hosted by the shell's `safeAreaBar` exactly as on
/// iOS. Selecting it opens the full player.
struct TVMiniPlayerBar: View {
    @Environment(PlayerViewModel.self) private var player

    @State private var showPlayer = false

    var body: some View {
        if let track = player.currentTrack {
            Button {
                showPlayer = true
            } label: {
                HStack(spacing: 20) {
                    artwork
                    VStack(alignment: .leading, spacing: 4) {
                        Text(track.name)
                            .font(.headline)
                            .lineLimit(1)
                        Text(player.eraName.isEmpty
                             ? player.artistName
                             : "\(player.artistName) · \(player.eraName)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Text("\(PlayerViewModel.formatTime(player.currentTime)) / \(PlayerViewModel.formatTime(player.duration))")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                    Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                }
                .padding(.horizontal, 40)
                .padding(.vertical, 18)
                .contentShape(Rectangle())
            }
            .buttonStyle(TVRowButtonStyle())
            .padding(.horizontal, 40)
            .glassEffect(in: .rect(cornerRadius: 18))
            .focusSection()
            .fullScreenCover(isPresented: $showPlayer) {
                TVNowPlayingView()
            }
        }
    }

    @ViewBuilder
    private var artwork: some View {
        Group {
            if !player.artUrl.isEmpty,
               let url = APIClient.shared.imageProxyURL(for: player.artUrl, width: 128) {
                CachedImage(url: url, maxPixelSize: 128) {
                    ArtworkPlaceholder(cornerRadius: 6)
                }
                .aspectRatio(contentMode: .fill)
            } else {
                ArtworkPlaceholder(cornerRadius: 6)
            }
        }
        .frame(width: 60, height: 60)
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}
