import SwiftUI

/// The queue. Rows can't be swiped or long-pressed on tvOS, so each carries an
/// explicit Remove button beside the play action.
struct TVQueueView: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 24) {
            HStack {
                Text("Queue (\(player.queue.count))")
                    .font(.largeTitle.bold())
                Spacer()
                if !player.queue.isEmpty {
                    Button("Clear", role: .destructive) { player.clearQueue() }
                }
                Button("Done") { dismiss() }
            }
            .focusSection()

            if player.queue.isEmpty {
                ContentUnavailableView(
                    "Queue Empty",
                    systemImage: "list.bullet",
                    description: Text("Open a song and choose Queue to add it.")
                )
                .frame(maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(Array(player.queue.enumerated()), id: \.element.id) { index, item in
                            HStack(spacing: 12) {
                                Button {
                                    player.playFromQueue(at: index)
                                } label: {
                                    HStack(spacing: 16) {
                                        Image(systemName: "play.circle")
                                            .foregroundStyle(.secondary)
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(item.version.name)
                                                .lineLimit(1)
                                            Text(item.eraName.isEmpty
                                                 ? item.artistName
                                                 : "\(item.artistName) · \(item.eraName)")
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                                .lineLimit(1)
                                        }
                                        Spacer()
                                    }
                                    .padding(.horizontal, 24)
                                    .padding(.vertical, 12)
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(TVRowButtonStyle())

                                Button(role: .destructive) {
                                    player.removeFromQueue(at: index)
                                } label: {
                                    Image(systemName: "trash")
                                        .padding(18)
                                        .contentShape(Rectangle())
                                }
                                .buttonStyle(TVRowButtonStyle())
                                .accessibilityLabel("Remove \(item.version.name) from queue")
                            }
                        }
                    }
                }
            }
        }
        .padding(60)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.lsBackground)
        .onExitCommand { dismiss() }
    }
}
