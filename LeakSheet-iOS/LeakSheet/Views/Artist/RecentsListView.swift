import SwiftUI

struct RecentsListView: View {
    let vm: ArtistViewModel
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onShowDescription: (DescriptionSheet.Payload) -> Void

    @Environment(PlayerViewModel.self) private var player

    var body: some View {
        let visible = vm.visibleRecents

        if visible.isEmpty {
            if vm.isFiltering {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 32)
            } else {
                ContentUnavailableView(
                    "No Recent Leaks",
                    systemImage: "clock",
                    description: Text("No versions carry a leak or file date.")
                )
                .padding(.top, 40)
            }
        } else {
            ForEach(visible.enumerated(), id: \.element.id) { idx, result in
              // Single root: LazyVStack can only template row identity from the ForEach ids
              // when the body is unary (see ArtistRowViews.swift).
              let startsGroup = idx == 0 || visible[idx - 1].era.name != result.era.name
              VStack(spacing: 0) {
                // Era group header — show when era changes
                if startsGroup {
                    HStack(spacing: 8) {
                        Text(result.era.name.uppercased())
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(vm.eraDisplay[result.era.name]?.readableHeader ?? .secondary)
                            // The name wins the row; the rule takes what is left.
                            .layoutPriority(1)
                        Rectangle()
                            .fill(Color.lsBorder)
                            .frame(height: 1)
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, idx == 0 ? 4 : 12)
                    .padding(.bottom, 2)
                }

                // Date label (only when it changes) sits inside the panel, so a group
                // reads as one surface.
                VStack(spacing: 0) {
                    let previous = idx > 0 ? visible[idx - 1].version : nil
                    let prevDate = previous.flatMap { $0.leakDate ?? $0.fileDate }
                    let thisDate = result.version.leakDate ?? result.version.fileDate
                    if let date = thisDate, !date.isEmpty, date != prevDate {
                        HStack(spacing: 4) {
                            Image(systemName: "calendar")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text(date)
                                .font(.caption.weight(.medium))
                                .foregroundStyle(.secondary)
                            Spacer()
                        }
                        .padding(.horizontal, 12)
                        .padding(.top, 8)
                    }

                    SongRowView(
                        song: result.song,
                        version: result.version,
                        artistName: artistName,
                        artistSlug: artistSlug,
                        sourceUrl: sourceUrl,
                        eraName: result.era.name,
                        eraArt: result.era.artUrl,
                        showVersionBadge: true,
                        // Swipe-to-play continues down the recents list like tap.
                        onPlay: { _ in
                            if let (items, idx) = vm.recentPlayback(for: result.id) {
                                player.playInList(items, startAt: idx)
                            }
                        },
                        onShowDescription: onShowDescription
                    )
                    .contentShape(Rectangle())
                    .accessibilityAddTraits(.isButton)
                    // Tap opens Details, never plays — see handleSongTap.
                    .onTapGesture {
                        onShowDescription(DescriptionSheet.Payload(
                            song: result.song, version: result.version,
                            artistName: artistName, artistSlug: artistSlug,
                            eraName: result.era.name, eraArt: result.era.artUrl
                        ))
                    }
                }
                // Same panel as the eras branch; no card above it, so the group rounds
                // at both ends.
                .songPanel(
                    vm.eraDisplay[result.era.name],
                    isFirst: startsGroup,
                    isLast: idx == visible.count - 1
                        || visible[idx + 1].era.name != result.era.name
                )
                .onAppear {
                    // Against the LIVE count, not the `visible` snapshot a fast scroll would append
                    // from repeatedly. Eight rows early so the next page lands in time.
                    if idx >= vm.visibleRecents.count - 8 {
                        vm.loadMoreRecents()
                    }
                }
              }
            }
        }
    }
}
