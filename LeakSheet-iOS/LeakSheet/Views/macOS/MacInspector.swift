#if os(macOS)
import SwiftUI

/// The trailing rail: Details and Queue in one panel, switched by a segmented
/// control.
///
/// Both used to be modal sheets *and* — for the queue — a second, separate
/// inspector, so the same content had two surfaces that could disagree. Here
/// there is one of each, neither of them modal: reading a song's details or
/// reordering the queue never blocks the window behind it.
struct MacInspector: View {
    @State private var ui = MacUIState.shared
    @Environment(ArtistViewModel.self) private var artistVM: ArtistViewModel?

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $ui.inspectorTab) {
                ForEach(MacUIState.InspectorTab.allCases) { tab in
                    Text(tab.title).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 12)
            .padding(.vertical, 8)

            Divider().overlay(Color.lsBorder)

            switch ui.inspectorTab {
            case .details:
                if let payload = ui.selectedSong {
                    SongDescriptionSheet(payload: payload, embedded: true)
                        .environment(artistVM)
                        .id(payload.id)
                } else {
                    ContentUnavailableView(
                        "No Song Selected",
                        systemImage: "info.circle",
                        description: Text("Select a song to see its versions, credits and links.")
                    )
                }
            case .queue:
                QueueSheet(embedded: true)
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            Color.clear.frame(height: ui.playerBarHeight)
        }
        .background(Color.lsBackground)
    }
}
#endif
