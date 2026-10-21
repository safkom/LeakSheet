import SwiftUI

/// Long-press actions for an era card: play, shuffle or queue the whole era.
struct EraContextMenu: View {
    let era: FilteredEra
    let artistName: String
    let artistSlug: String
    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        if !era.streamableVersions.isEmpty {
            Button {
                player.playEra(era, artistName: artistName, artistSlug: artistSlug)
            } label: {
                Label("Play Era", systemImage: "play.fill")
            }
            Button {
                player.shuffleEra(era, artistName: artistName, artistSlug: artistSlug)
            } label: {
                Label("Shuffle Era", systemImage: "shuffle")
            }
            Button {
                player.queueEra(era, artistName: artistName, artistSlug: artistSlug)
            } label: {
                Label("Add Era to Queue", systemImage: "text.append")
            }
        }
    }
}
