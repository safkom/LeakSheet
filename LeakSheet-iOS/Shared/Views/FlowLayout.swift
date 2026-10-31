import SwiftUI

/// A wrapping HStack: lays subviews left-to-right, wrapping when the next would
/// overflow, so pills wrap at large Dynamic Type sizes instead of clipping.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    struct Cache {
        var width: CGFloat = .nan
        var offsets: [CGPoint] = []
        var sizes: [CGSize] = []
        var size: CGSize = .zero
    }

    func makeCache(subviews: Subviews) -> Cache { Cache() }

    func updateCache(_ cache: inout Cache, subviews: Subviews) {
        // Subview composition may have changed — invalidate so the next pass recomputes.
        cache.width = .nan
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> CGSize {
        ensureLayout(proposal: proposal, subviews: subviews, cache: &cache).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) {
        let proposed = ProposedViewSize(width: bounds.width, height: bounds.height)
        let result = ensureLayout(proposal: proposed, subviews: subviews, cache: &cache)
        for (index, offset) in result.offsets.enumerated() where index < subviews.count {
            // Clamped placement size — see DECISIONS.md::FlowLayout.swift::clamped-sizing
            let placedSize = index < result.sizes.count ? result.sizes[index] : nil
            subviews[index].place(
                at: CGPoint(x: bounds.minX + offset.x, y: bounds.minY + offset.y),
                proposal: placedSize.map { ProposedViewSize(width: $0.width, height: $0.height) } ?? .unspecified
            )
        }
    }

    private func ensureLayout(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> Cache {
        let width = proposal.width ?? .infinity
        if cache.width == width, cache.offsets.count == subviews.count {
            return cache
        }
        let result = layout(proposal: proposal, subviews: subviews)
        cache = Cache(width: width, offsets: result.offsets, sizes: result.sizes, size: result.size)
        return cache
    }

    private func layout(proposal: ProposedViewSize, subviews: Subviews) -> (
        offsets: [CGPoint],
        sizes: [CGSize],
        size: CGSize
    ) {
        let maxWidth = proposal.width ?? .infinity
        var offsets: [CGPoint] = []
        var sizes: [CGSize] = []
        var xPos: CGFloat = 0
        var yPos: CGFloat = 0
        var rowHeight: CGFloat = 0
        var maxX: CGFloat = 0

        for subview in subviews {
            // Clamped measurement proposal — see DECISIONS.md::FlowLayout.swift::clamped-sizing
            var size = subview.sizeThatFits(ProposedViewSize(width: maxWidth, height: nil))
            size.width = min(size.width, maxWidth)
            // The reported width is the row's own width; placement can hand back a hair less
            // after pixel rounding, which must not wrap the last item onto an unmeasured row.
            if xPos + size.width > maxWidth + 1 && xPos > 0 {
                xPos = 0
                yPos += rowHeight + spacing
                rowHeight = 0
            }
            offsets.append(CGPoint(x: xPos, y: yPos))
            sizes.append(size)
            rowHeight = max(rowHeight, size.height)
            xPos += size.width + spacing
            maxX = max(maxX, xPos - spacing)
        }

        // Clamp reported width to the available space so parents (especially LazyVStack)
        // don't get an inflated size from one over-wide child.
        let clampedWidth = maxWidth < .infinity ? min(maxX, maxWidth) : maxX
        return (offsets, sizes, CGSize(width: clampedWidth, height: yPos + rowHeight))
    }
}
