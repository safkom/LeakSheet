import SwiftUI

extension SongDescriptionSheet {
    // MARK: - Chrome

    @ToolbarContentBuilder
    var chromeToolbar: some ToolbarContent {
        // Actions go trailing, not in the leading slot other sheets use to close;
        // Done is the confirmation.
        ToolbarItem(placement: .primaryAction) {
            Menu {
                overflowItems
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .accessibilityLabel("More options")
        }
        ToolbarItem(placement: .confirmationAction) {
            Button("Done") { dismiss() }
        }
    }

    /// Secondary actions — the toolbar menu when presented, the bottom-bar
    /// menu when embedded.
    @ViewBuilder
    var overflowItems: some View {
        if canStream {
            Button {
                play()
            } label: {
                Label("Play", systemImage: "play.fill")
            }
            Button {
                player.addToQueue(
                    active.version,
                    artistName: payload.artistName,
                    eraName: active.eraName,
                    artUrl: active.eraArt ?? "",
                    artistSlug: payload.artistSlug ?? ""
                )
                Haptics.light()
            } label: {
                Label("Add to Queue", systemImage: "text.append")
            }
        }
        Button {
            toggleFavourite()
            Haptics.light()
        } label: {
            Label("Favourite", systemImage: "heart")
        }
        if let link = active.version.links?.first {
            Button {
                Pasteboard.copy(link)
            } label: {
                Label("Copy Link", systemImage: "doc.on.doc")
            }
        }
    }
}
