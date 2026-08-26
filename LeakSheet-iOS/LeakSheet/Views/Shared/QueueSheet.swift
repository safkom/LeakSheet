import SwiftUI

/// Queue panel showing upcoming tracks with reorder/remove.
struct QueueSheet: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss

    /// Set when hosted as the macOS inspector panel rather than presented as a
    /// sheet — the host supplies the navigation chrome.
    var embedded = false

    private static let emptyHint: String = {
        #if os(macOS)
        "Hover a song and use its ⋯ menu, or right-click it."
        #else
        "Swipe left on a song to add it to the queue."
        #endif
    }()

    var body: some View {
        if embedded {
            // The inspector this is hosted in sits OUTSIDE the detail column's
            // navigation container, so `navigationTitle`/`toolbar` here would
            // not label the panel — they would overwrite the window's own title
            // and drop Clear into the main toolbar. Inline header instead.
            VStack(spacing: 0) {
                HStack {
                    Text("Queue (\(player.queue.count))")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    if !player.queue.isEmpty {
                        Button("Clear") { player.clearQueue() }
                            .buttonStyle(.plain)
                            .font(.caption)
                            .foregroundStyle(Color.lsError)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)

                Divider().overlay(Color.lsBorder)

                content
            }
        } else {
            NavigationStack {
                content
                    .navigationTitle("Queue (\(player.queue.count))")
                    #if os(iOS)
                    .toolbarTitleDisplayMode(.inline)
                    #endif
                    .toolbar { chrome }
            }
            .presentationBackground(.ultraThinMaterial)
        }
    }

    private var content: some View {
            Group {
                if player.queue.isEmpty {
                    ContentUnavailableView(
                        "Queue Empty",
                        systemImage: "list.bullet",
                        description: Text(Self.emptyHint)
                    )
                } else {
                    List {
                        ForEach(Array(player.queue.enumerated()), id: \.element.id) { index, item in
                            HStack(spacing: 10) {
                                // Era art thumbnail
                                if !item.artUrl.isEmpty {
                                    CachedImage(url: APIClient.shared.imageProxyURL(for: item.artUrl, width: 128), maxPixelSize: 128) {
                                        queueArtPlaceholder
                                    }
                                    .frame(width: 40, height: 40)
                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                } else {
                                    queueArtPlaceholder
                                        .frame(width: 40, height: 40)
                                }

                                VStack(alignment: .leading, spacing: 3) {
                                    HStack(spacing: 5) {
                                        if let b = item.version.badge, let badge = Badge(rawValue: b) {
                                            Text(badge.emoji)
                                                .font(.caption)
                                                .accessibilityLabel(badge.label)
                                        }
                                        Text(item.version.name)
                                            .font(.subheadline)
                                            .lineLimit(1)
                                    }
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
                                .accessibilityLabel("Play \(item.version.name)")
                            }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    player.removeFromQueue(at: index)
                                } label: {
                                    Image(systemName: "trash")
                                }
                                .accessibilityLabel("Remove from queue")
                            }
                            // macOS ignores swipeActions, so the inspector's
                            // queue had no per-item remove at all — Clear was
                            // the only way to take one track out.
                            .contextMenu {
                                Button("Remove from Queue", systemImage: "trash", role: .destructive) {
                                    player.removeFromQueue(at: index)
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
    }

    @ToolbarContentBuilder
    private var chrome: some ToolbarContent {
        ToolbarItem(placement: .cancellationAction) {
            if !player.queue.isEmpty {
                Button("Clear") { player.clearQueue() }
                    .foregroundStyle(Color.lsError)
            }
        }
        #if os(iOS)
        // .onMove needs edit mode on iOS, and there was no way to enter it —
        // so the whole reorder path (moveInQueue and its test) was unreachable
        // on the platform that has it. macOS Lists reorder by drag natively
        // and need no button.
        ToolbarItem(placement: .primaryAction) {
            // Shown whenever the queue is non-empty, not only when it has 2+
            // items: gated on `> 1`, removing rows down to one while editing
            // took the button away with edit mode still active, and nothing
            // else exits it.
            if !player.queue.isEmpty {
                EditButton()
            }
        }
        #endif
        ToolbarItem(placement: .primaryAction) {
            Button("Done") { dismiss() }
        }
    }

    private var queueArtPlaceholder: some View {
        ArtworkPlaceholder(cornerRadius: 6)
            .frame(width: 40, height: 40)
    }
}
