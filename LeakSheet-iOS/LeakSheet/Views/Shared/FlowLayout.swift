import SwiftUI

/// A wrapping HStack: lays subviews left-to-right and wraps to the next row when
/// the next subview would overflow the proposed width. Used for badge / quality
/// / credit pills so they wrap to a second line at large Dynamic Type sizes
/// instead of clipping off the trailing edge.
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
            // Place each subview with the same (clamped) size it was measured
            // at — NOT .unspecified. An unspecified placement proposal lets a
            // wrap-capable pill re-expand to its full single-line intrinsic
            // width and clip off the trailing edge; proposing the measured
            // size makes its inner Text actually wrap to the rows we sized for.
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

    private func layout(proposal: ProposedViewSize, subviews: Subviews) -> (offsets: [CGPoint], sizes: [CGSize], size: CGSize) {
        let maxWidth = proposal.width ?? .infinity
        var offsets: [CGPoint] = []
        var sizes: [CGSize] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var maxX: CGFloat = 0

        for subview in subviews {
            // Measure against maxWidth, not .unspecified — an .unspecified
            // proposal gives Text its full intrinsic (single-line) width, so
            // a long credit pill placed first in a row would report a size
            // wider than the container and never trigger the wrap check
            // below. Clamping the proposal lets wrap-capable subviews (Text)
            // report a narrower, multi-line size instead.
            var size = subview.sizeThatFits(ProposedViewSize(width: maxWidth, height: nil))
            size.width = min(size.width, maxWidth)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            offsets.append(CGPoint(x: x, y: y))
            sizes.append(size)
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            maxX = max(maxX, x - spacing)
        }

        // Clamp reported width to the available space so parent containers
        // (especially LazyVStack) don't receive an inflated size when a single
        // child is wider than the proposal (e.g. a very long credit tag).
        let clampedWidth = maxWidth < .infinity ? min(maxX, maxWidth) : maxX
        return (offsets, sizes, CGSize(width: clampedWidth, height: y + rowHeight))
    }
}
