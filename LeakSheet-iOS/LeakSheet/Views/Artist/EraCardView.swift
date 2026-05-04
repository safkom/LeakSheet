import SwiftUI

/// Collapsible era card header — single tinted container, hairline border on top + sides.
/// When expanded, the bottom is square and flushes into the song list below.
struct EraCardView: View {
    let era: Era
    let expanded: Bool
    let stats: ArtistViewModel.Stats
    var onTap: () -> Void
    var onColorExtracted: ((Color) -> Void)?

    @State private var dominantColor: Color?

    private let cornerRadius: CGFloat = 16

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .center, spacing: 14) {
                    coverArt
                    titleBlock
                    Spacer(minLength: 8)
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(titleColor.opacity(0.6))
                        .accessibilityHidden(true)
                }

                if expanded {
                    if let alts = era.altNames, !alts.isEmpty {
                        Text(alts.joined(separator: " · "))
                            .font(.footnote)
                            .foregroundStyle(bodyColor.opacity(0.85))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    if let desc = era.description, !desc.isEmpty {
                        Text(desc)
                            .font(.subheadline)
                            .foregroundStyle(bodyColor)
                            .lineSpacing(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            // Liquid Glass + tinted gradient:
            // glass sits directly behind content (frosted refraction layer),
            // gradient is the deeper background that bleeds through the glass.
            .glassEffect(.regular, in: cardShape)
            .background {
                cardShape.fill(eraBackground)
            }
            .overlay {
                EraCardBorder(cornerRadius: cornerRadius, expanded: expanded)
                    .stroke(borderColor, lineWidth: 1)
            }
            .clipShape(cardShape)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(era.name)
        .accessibilityHint(expanded ? "Collapse era" : "Expand era")
        .accessibilityAddTraits(.isButton)
    }

    // MARK: - Pieces

    private var coverArt: some View {
        Group {
            if let artUrl = era.artUrl, let url = APIClient.shared.imageProxyURL(for: artUrl) {
                CachedEraImage(url: url, eraName: era.name) { color in
                    dominantColor = color
                    onColorExtracted?(color)
                }
            } else {
                Image(systemName: "music.note")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color.lsCard)
            }
        }
        .frame(width: expanded ? 96 : 64, height: expanded ? 96 : 64)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .shadow(color: .black.opacity(0.35), radius: 8, x: 0, y: 4)
    }

    private var titleBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(era.name)
                .font((expanded ? Font.title2 : .title3).weight(.semibold))
                .tracking(-0.3)
                .foregroundStyle(titleColor)
                .lineLimit(expanded ? 3 : 2)
                .multilineTextAlignment(.leading)

            // Collapsed: show alts inline under title (no A.K.A. prefix)
            if !expanded, let alts = era.altNames, !alts.isEmpty {
                Text(alts.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(bodyColor.opacity(0.85))
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
    }

    // MARK: - Shapes

    private var cardShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: cornerRadius,
            bottomLeadingRadius: expanded ? 0 : cornerRadius,
            bottomTrailingRadius: expanded ? 0 : cornerRadius,
            topTrailingRadius: cornerRadius
        )
    }

    // MARK: - Colors

    private var titleColor: Color {
        guard let color = dominantColor else { return .primary }
        let (r, g, b) = color.rgbComponents
        let effective = Color(red: r * 0.48, green: g * 0.48, blue: b * 0.48)
        return Color.preferredText(on: effective)
    }

    private var bodyColor: Color {
        titleColor.opacity(0.78)
    }

    private var borderColor: Color {
        titleColor.opacity(0.18)
    }

    private var eraBackground: some ShapeStyle {
        if let color = dominantColor {
            let (r, g, b) = color.rgbComponents
            let d1 = Color(red: r * 0.55, green: g * 0.55, blue: b * 0.55).opacity(0.95)
            let d2 = Color(red: r * 0.40, green: g * 0.40, blue: b * 0.40).opacity(0.90)
            return AnyShapeStyle(
                LinearGradient(
                    colors: [d1, d2],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
        }
        return AnyShapeStyle(Color.lsCard)
    }
}

// MARK: - Border shape

/// Era card hairline border. Draws top + sides + rounded top corners always,
/// and the rounded bottom corners + bottom edge only when collapsed. When
/// expanded, the border opens at the bottom so the card flushes into the
/// song list without a visible seam.
private struct EraCardBorder: Shape {
    let cornerRadius: CGFloat
    let expanded: Bool

    func path(in rect: CGRect) -> Path {
        var path = Path()
        let r = cornerRadius

        if expanded {
            // Top-left corner
            path.move(to: CGPoint(x: rect.minX, y: rect.maxY))
            path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + r))
            path.addArc(
                center: CGPoint(x: rect.minX + r, y: rect.minY + r),
                radius: r,
                startAngle: .degrees(180),
                endAngle: .degrees(270),
                clockwise: false
            )
            // Top edge → top-right corner
            path.addLine(to: CGPoint(x: rect.maxX - r, y: rect.minY))
            path.addArc(
                center: CGPoint(x: rect.maxX - r, y: rect.minY + r),
                radius: r,
                startAngle: .degrees(270),
                endAngle: .degrees(0),
                clockwise: false
            )
            // Right edge down to bottom (bottom edge intentionally omitted)
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        } else {
            path.addRoundedRect(in: rect, cornerSize: CGSize(width: r, height: r))
        }

        return path
    }
}

// MARK: - Cached era image

/// Displays an era image from ImageCache (instant if prefetched), falls back to network load.
/// Triggers color extraction once the image is available.
private struct CachedEraImage: View {
    let url: URL
    let eraName: String
    var onColorExtracted: (Color) -> Void

    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
            } else {
                Color.lsCard
            }
        }
        .task(id: url) {
            if let cached = await ImageCache.shared.cachedImage(for: url) {
                image = cached
                extractColor(from: cached)
                return
            }
            if let loaded = await ImageCache.shared.loadImage(from: url) {
                image = loaded
                extractColor(from: loaded)
            }
        }
    }

    private func extractColor(from img: UIImage) {
        Task {
            if let color = await EraColorExtractor.shared.extractColor(fromImage: img, eraName: eraName) {
                await MainActor.run { onColorExtracted(color) }
            }
        }
    }
}
