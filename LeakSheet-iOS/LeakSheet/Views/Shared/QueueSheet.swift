import SwiftUI

/// Queue panel showing upcoming tracks with reorder/remove.
struct QueueSheet: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if player.queue.isEmpty {
                    ContentUnavailableView(
                        "Queue Empty",
                        systemImage: "list.bullet",
                        description: Text("Swipe right on a song to add it to the queue.")
                    )
                } else {
                    List {
                        ForEach(Array(player.queue.enumerated()), id: \.element.id) { index, item in
                            HStack(spacing: 10) {
                                // Era art thumbnail
                                if !item.artUrl.isEmpty {
                                    CachedImage(url: APIClient.shared.imageProxyURL(for: item.artUrl)) {
                                        queueArtPlaceholder
                                    }
                                    .frame(width: 40, height: 40)
                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                } else {
                                    queueArtPlaceholder
                                        .frame(width: 40, height: 40)
                                }

                                VStack(alignment: .leading, spacing: 3) {
                                    Text(item.version.name)
                                        .font(.subheadline)
                                        .lineLimit(1)
                                    Text(item.eraName.isEmpty ? item.artistName : "\(item.artistName) · \(item.eraName)")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                    // Quality/availability badges
                                    BadgeRowView(version: item.version)
                                    // Credits (feat. only for compactness)
                                    if let feat = item.version.featuring, !feat.isEmpty {
                                        HStack(spacing: 3) {
                                            Text("feat.")
                                                .font(.caption2.weight(.medium))
                                                .foregroundStyle(.tertiary)
                                            Text(feat)
                                                .font(.caption2.weight(.medium))
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                }

                                Spacer()

                                Button {
                                    player.playFromQueue(at: index)
                                } label: {
                                    Image(systemName: "play.circle")
                                        .foregroundStyle(.secondary)
                                }
                                .buttonStyle(.plain)
                            }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    player.removeFromQueue(at: index)
                                } label: {
                                    Image(systemName: "trash")
                                }
                            }
                        }
                        .onMove { from, to in
                            player.moveInQueue(from: from, to: to)
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }
            }
            .background(Color.lsBackground)
            .navigationTitle("Queue (\(player.queue.count))")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if !player.queue.isEmpty {
                        Button("Clear") {
                            player.clearQueue()
                        }
                        .foregroundStyle(.red)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationBackground(.ultraThinMaterial)
    }

    private var queueArtPlaceholder: some View {
        Image(systemName: "music.note")
            .foregroundStyle(.secondary)
            .frame(width: 40, height: 40)
            .background(Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}
