import SwiftUI

/// Queue panel showing upcoming tracks with reorder/remove.
struct QueueSheet: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss

    /// Set when hosted as the macOS inspector panel rather than presented as a
    /// sheet — the host supplies the navigation chrome.
    var embedded = false

    /// Clearing drops every queued track with no undo, so it asks first.
    @State private var confirmingClear = false

    private static let emptyHint: String = {
        #if os(macOS)
        "Hover a song and use its ⋯ menu, or right-click it."
        #else
        "Swipe left on a song to add it to the queue."
        #endif
    }()

    var body: some View {
        Group {
            if embedded {
                // Inline header: see DECISIONS.md::QueueSheet.swift::embedded-chrome
                VStack(spacing: 0) {
                    HStack {
                        Text("Queue (\(player.queue.count))")
                            .font(.subheadline.weight(.semibold))
                        Spacer()
                        if !player.queue.isEmpty {
                            Button("Clear", role: .destructive) { confirmingClear = true }
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
            }
        }
        .confirmationDialog(
            "Clear the queue?",
            isPresented: $confirmingClear,
            titleVisibility: .visible
        ) {
            Button("Clear ^[\(player.queue.count) Track](inflect: true)", role: .destructive) {
                player.clearQueue()
            }
        } message: {
            Text("This can't be undone.")
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
                        ForEach(player.queue) { item in
                            row(item)
                        }
                        // Drag to reorder with no edit mode (iOS 27's reorderable container).
                        .reorderable()
                    }
                    .reorderContainer(for: QueueItem.self) { difference in
                        applyReorder(difference)
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }
            }
            .background(Color.lsBackground)
    }

    private func row(_ item: QueueItem) -> some View {
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
                if let index = index(of: item) { player.playFromQueue(at: index) }
            } label: {
                Image(systemName: "play.circle")
                    .foregroundStyle(.secondary)
                    // Metrics.hitTarget: 44 pt on touch (the HIG minimum), smaller for a pointer.
                    .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Play \(item.version.name)")
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) {
                if let index = index(of: item) { player.removeFromQueue(at: index) }
            } label: {
                Image(systemName: "trash")
            }
            .accessibilityLabel("Remove from queue")
        }
        // macOS ignores swipeActions, so per-item remove
        // lives in the context menu too.
        .contextMenu {
            Button("Remove from Queue", systemImage: "trash", role: .destructive) {
                if let index = index(of: item) { player.removeFromQueue(at: index) }
            }
        }
        // Dragging is the only visible way to reorder, which VoiceOver and
        // Switch Control can't do.
        .accessibilityAction(named: "Move Up") { move(item, by: -1) }
        .accessibilityAction(named: "Move Down") { move(item, by: 1) }
    }

    /// The item's CURRENT position, resolved at tap time: a captured row index goes
    /// stale as soon as the queue advances or is reordered.
    private func index(of item: QueueItem) -> Int? {
        player.queue.firstIndex { $0.id == item.id }
    }

    /// `moveInQueue` takes a destination in the pre-move queue, so moving down
    /// one lands two past the source.
    private func move(_ item: QueueItem, by offset: Int) {
        guard let index = index(of: item) else { return }
        let target = index + offset
        guard player.queue.indices.contains(target) else { return }
        player.moveInQueue(from: IndexSet(integer: index), to: offset > 0 ? target + 1 : target)
    }

    /// Translate SwiftUI's reorder description into `moveInQueue`, which has
    /// `.onMove` semantics: a destination index into the queue as it stood
    /// before the move. `.before(id)` is that item's index; `.end` is the count.
    private func applyReorder(_ difference: ReorderDifference<QueueItem.ID, ReorderableSingleCollectionIdentifier>) {
        let queue = player.queue
        let source = IndexSet(difference.sources.compactMap { id in
            queue.firstIndex { $0.id == id }
        })
        let destination: Int
        switch difference.destination.position {
        case .before(let id):
            destination = queue.firstIndex { $0.id == id } ?? queue.count
        case .end:
            destination = queue.count
        }
        player.moveInQueue(from: source, to: destination)
    }

    @ToolbarContentBuilder
    private var chrome: some ToolbarContent {
        // .destructiveAction, not the leading slot where Cancel lives; it also asks first.
        // The condition sits outside the item, or an empty glass capsule would remain.
        if !player.queue.isEmpty {
            ToolbarItem(placement: .destructiveAction) {
                // role alone renders neutral text in the glass toolbar.
                Button("Clear", role: .destructive) { confirmingClear = true }
                    .foregroundStyle(Color.lsError)
            }
        }
        ToolbarItem(placement: .confirmationAction) {
            Button("Done") { dismiss() }
        }
    }

    private var queueArtPlaceholder: some View {
        ArtworkPlaceholder(cornerRadius: 6)
            .frame(width: 40, height: 40)
    }
}
