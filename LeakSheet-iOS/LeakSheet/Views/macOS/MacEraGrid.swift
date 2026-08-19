#if os(macOS)
import SwiftUI

/// Era browser: a grid of covers. The iOS accordion puts one full-width bar per
/// era, which on a desktop window is a column of mostly-empty rows — a grid uses
/// the width the window actually has and shows a dozen covers at once.
///
/// Picking a tile drills into that era's song list (`MacArtistView` swaps the
/// pane); there is no in-place expansion.
struct MacEraGrid: View {
    let vm: ArtistViewModel
    let onSelect: (String) -> Void

    private static let columns = [GridItem(.adaptive(minimum: 168, maximum: 240), spacing: 16)]

    var body: some View {
        if vm.content.eras.isEmpty {
            ContentUnavailableView {
                Label(
                    hasActiveFilters ? "No Matches" : "No Songs",
                    systemImage: hasActiveFilters ? "line.3.horizontal.decrease.circle" : "music.note.list"
                )
            } description: {
                Text(hasActiveFilters
                     ? "No songs match the current filters."
                     : "This tracker has no songs yet.")
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 48)
        } else {
            LazyVGrid(columns: Self.columns, spacing: 16) {
                ForEach(vm.content.eras) { filtered in
                    MacEraTile(
                        era: filtered.era,
                        songCount: filtered.allSongs.count,
                        displayColors: vm.eraDisplay[filtered.era.name],
                        onSelect: { onSelect(filtered.era.name) },
                        onColorExtracted: { vm.setEraColor(eraName: filtered.era.name, dominant: $0) }
                    )
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
    }

    /// Must list EVERY chip that can empty the list, or the empty state claims
    /// "No Songs" (tracker is empty) when the truth is "No Matches".
    private var hasActiveFilters: Bool {
        vm.bestOf || vm.worstOf || vm.grails || vm.noSnippets
    }
}

/// One era cover with its name and song count underneath.
private struct MacEraTile: View {
    let era: Era
    let songCount: Int
    let displayColors: EraDisplayColors?
    let onSelect: () -> Void
    let onColorExtracted: (Color) -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading, spacing: 8) {
                cover
                    .aspectRatio(1, contentMode: .fill)
                    .frame(maxWidth: .infinity)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay {
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(displayColors?.border ?? Color.lsBorder, lineWidth: 1)
                    }
                    .shadow(color: .black.opacity(hovering ? 0.45 : 0.25), radius: hovering ? 12 : 6, y: 4)
                    .scaleEffect(hovering ? 1.02 : 1)

                VStack(alignment: .leading, spacing: 2) {
                    Text(era.name)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    Text("\(songCount) song\(songCount == 1 ? "" : "s")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .animation(.easeOut(duration: 0.12), value: hovering)
        .onHover { hovering = $0 }
        .accessibilityLabel("\(era.name), \(songCount) songs")
        .accessibilityHint("Show this era's songs")
        .help(era.altNames?.joined(separator: " · ") ?? era.name)
    }

    @ViewBuilder
    private var cover: some View {
        if let artUrl = era.artUrl,
           let url = APIClient.shared.imageProxyURL(for: artUrl, width: 480) {
            MacEraCover(url: url, cacheKey: artUrl, onColorExtracted: onColorExtracted)
        } else {
            ArtworkPlaceholder(cornerRadius: 0)
        }
    }
}

/// Loads an era cover and reports its dominant colour once, so the grid seeds
/// the same `eraDisplay` cache the song list reads.
private struct MacEraCover: View {
    let url: URL
    let cacheKey: String
    let onColorExtracted: (Color) -> Void

    @State private var image: CGImage?

    var body: some View {
        Group {
            if let image {
                Image(decorative: image, scale: 1)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
            } else {
                ArtworkPlaceholder(cornerRadius: 0)
            }
        }
        .task(id: url) {
            if let cached = await ImageCache.shared.cachedImage(for: url, maxPixelSize: 480) {
                image = cached
                extract(cached)
                return
            }
            if let loaded = await ImageCache.shared.loadImage(from: url, maxPixelSize: 480) {
                image = loaded
                extract(loaded)
            }
        }
    }

    private func extract(_ img: CGImage) {
        Task {
            if let color = await EraColorExtractor.shared.extractColor(fromImage: img, cacheKey: cacheKey) {
                await MainActor.run { onColorExtracted(color) }
            }
        }
    }
}
#endif
