import SwiftUI

/// A whole-era playback action, shared by the long-press menu and VoiceOver.
struct EraAction: Identifiable {
    let id: String
    let systemImage: String
    let run: () -> Void

    /// "Era Info" when `onInfo` is given, then playback, which is left out when nothing in the
    /// era streams. Playback acts on the filtered era, like the Mac header's Play.
    static func all(for era: FilteredEra, artistName: String, artistSlug: String, player: PlayerViewModel,
                    onInfo: (() -> Void)? = nil) -> [EraAction] {
        let info = onInfo.map { [EraAction(id: "Era Info", systemImage: "info.circle", run: $0)] } ?? []
        guard era.allSongs.contains(where: { $0.versions.contains(where: \.isStreamable) }) else { return info }
        return info + [
            EraAction(id: "Play Era", systemImage: "play.fill") {
                Haptics.light()
                player.playEra(era, artistName: artistName, artistSlug: artistSlug)
            },
            EraAction(id: "Shuffle Era", systemImage: "shuffle") {
                Haptics.light()
                player.shuffleEra(era, artistName: artistName, artistSlug: artistSlug)
            },
            EraAction(id: "Era Radio", systemImage: "dot.radiowaves.left.and.right") {
                Haptics.light()
                player.playEraRadio(era, artistName: artistName, artistSlug: artistSlug)
            },
            EraAction(id: "Add Era to Queue", systemImage: "text.append") {
                Haptics.light()
                player.queueEra(era, artistName: artistName, artistSlug: artistSlug)
            }
        ]
    }
}

/// Long-press actions for an era card: play, shuffle or queue the whole era.
struct EraContextMenu: View {
    let actions: [EraAction]

    var body: some View {
        ForEach(actions) { action in
            Button(action: action.run) {
                Label(action.id, systemImage: action.systemImage)
            }
        }
    }
}
