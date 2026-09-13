import SwiftUI

/// Queue panel showing upcoming tracks with reorder/remove.
struct QueueSheet: View {
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss

    /// Set when hosted as the macOS inspector panel rather than presented as a
    /// sheet — the host supplies the navigation chrome.
    var embedded = false

    /// Clearing drops every queued track with no undo, so it asks first — the
    /// same as Favourites' Remove All and Recents' Clear already did.
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
                .presentationBackground(.ultraThinMaterial)
            }
        }
        .confirmationDialog(
            "Clear the queue?",
            isPresented: $confirmingClear,
            titleVisibility: .visible
        ) {
            Button("Clear \(player.queue.count) Tracks", role: .destructive) {
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
                        // Drag to reorder, with no edit mode. `.onMove` needed
                        // one on iOS, so an EditButton existed only to make
                        // reordering reachable; iOS 27's reorderable container
                        // does it directly, as the Music app's queue does.
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
                    // The bare glyph was a ~20 pt target. Metrics.hitTarget is
                    // 44 pt on touch, the HIG minimum, and smaller for a pointer.
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
        // macOS ignores swipeActions, so the inspector's
        // queue had no per-item remove at all — Clear was
        // the only way to take one track out.
        .contextMenu {
            Button("Remove from Queue", systemImage: "trash", role: .destructive) {
                if let index = index(of: item) { player.removeFromQueue(at: index) }
            }
        }
    }

    /// The item's CURRENT position. Resolved at tap time rather than captured
    /// when the row rendered: a row's index goes stale the moment the queue
    /// advances or is reordered, and acting on it removed or played the wrong
    /// track.
    private func index(of item: QueueItem) -> Int? {
        player.queue.firstIndex { $0.id == item.id }
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
        // Clear used to sit in .cancellationAction — the leading slot where
        // every other sheet in the app puts Cancel or Close — so reaching for
        // "back out" wiped the queue. .destructiveAction is the placement meant
        // for it; it also asks before clearing.
        ToolbarItem(placement: .destructiveAction) {
            if !player.queue.isEmpty {
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
