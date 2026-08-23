import SwiftUI

/// Collapsible era card header — single tinted container, hairline border on top + sides.
/// When expanded, the bottom is square and flushes into the song list below.
struct EraCardView: View {
    let era: Era
    let expanded: Bool
    /// Precomputed display colors (derived once per era when the dominant
    /// color is extracted) — nil until the first extraction lands.
    var displayColors: EraDisplayColors?
    /// Optional line under the title. Content-tab pages (Misc / Released /
    /// Stems / Fakes) use it for the entry count; the main era list has no
    /// subtitle and passes nil.
    var subtitle: String?
    var onTap: () -> Void
    var onColorExtracted: ((Color) -> Void)?

    private let cornerRadius: CGFloat = 16

    /// Collapsed by default. An era blurb runs to a full screen on the bigger
    /// trackers, so expanding an era used to show a wall of prose and push
    /// every song below the fold — the opposite of what tapping an era is for.
    @State private var descriptionExpanded = false

    /// Long enough that collapsing earns its "More" control. Shorter blurbs
    /// render whole, so the toggle never appears next to text it would not
    /// actually shorten.
    private let descriptionCollapseThreshold = 180
    private let descriptionCollapsedLines = 3

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Only the header toggles the era. The description below needs its
            // own control, and a Button inside another Button's label never
            // receives taps.
            Button(action: onTap) {
                HStack(alignment: .center, spacing: 14) {
                    coverArt
                    titleBlock
                    Spacer(minLength: 8)
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(titleColor.opacity(0.6))
                        .accessibilityHidden(true)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(era.name)
            .accessibilityHint(expanded ? "Collapse era" : "Expand era")
            .accessibilityAddTraits(.isButton)

            if expanded {
                if let alts = era.altNames, !alts.isEmpty {
                    altNamesLabel(alts, lineLimit: nil)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if let desc = era.description, !desc.isEmpty {
                    descriptionBlock(desc)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        // Glass + gradient layering — see DECISIONS.md::EraCardView.swift::glass-gradient-layering
        .glassEffect(.regular, in: .rect(cornerRadius: cornerRadius))
        .background {
            cardShape.fill(eraBackground)
        }
        .overlay {
            EraCardBorder(cornerRadius: cornerRadius, expanded: expanded)
                .stroke(borderColor, lineWidth: 1)
        }
        .clipShape(cardShape)
        .rowHoverHighlight()
    }

    @ViewBuilder
    private func descriptionBlock(_ desc: String) -> some View {
        let isLong = desc.count > descriptionCollapseThreshold
        VStack(alignment: .leading, spacing: 6) {
            Text(desc)
                .font(.subheadline)
                .foregroundStyle(bodyColor)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
                .lineLimit(isLong && !descriptionExpanded ? descriptionCollapsedLines : nil)

            if isLong {
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        descriptionExpanded.toggle()
                    }
                } label: {
                    Text(descriptionExpanded ? "Less" : "More")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(titleColor)
                        .padding(.vertical, 4)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(descriptionExpanded ? "Show less of the era description" : "Show the full era description")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Pieces

    private var coverArt: some View {
        Group {
            if let artUrl = era.artUrl,
               let url = APIClient.shared.imageProxyURL(for: artUrl, width: 320) {
                CachedEraImage(url: url, cacheKey: artUrl) { color in
                    onColorExtracted?(color)
                }
            } else {
                ArtworkPlaceholder(cornerRadius: 0)
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

            if !expanded, let alts = era.altNames, !alts.isEmpty {
                altNamesLabel(alts, lineLimit: 1)
            }

            if let subtitle {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(bodyColor.opacity(0.85))
            }
        }
    }

    /// Alt era names, dimmer than the era title so they read as aliases.
    /// The "A.K.A." prefix is gone — it repeated on every card, and the
    /// styling already says the same thing. VoiceOver still spells it out.
    private func altNamesLabel(_ alts: [String], lineLimit: Int?) -> some View {
        Text(alts.joined(separator: " · "))
            .font(.caption)
            .foregroundStyle(bodyColor.opacity(0.85))
            .lineLimit(lineLimit)
            .truncationMode(.tail)
            .accessibilityLabel("Also known as \(alts.joined(separator: ", "))")
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

    // MARK: - Colors (precomputed in EraDisplayColors — plain reads here)

    private var titleColor: Color {
        displayColors?.title ?? .primary
    }

    private var bodyColor: Color {
        displayColors?.body ?? .primary.opacity(0.78)
    }

    private var borderColor: Color {
        displayColors?.border ?? .primary.opacity(0.18)
    }

    private var eraBackground: some ShapeStyle {
        if let colors = displayColors {
            return AnyShapeStyle(
                LinearGradient(
                    colors: [colors.gradientTop, colors.gradientBottom],
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

    nonisolated func path(in rect: CGRect) -> Path {
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
    /// The era's raw (unproxied) art URL — unique per image, unlike era name.
    let cacheKey: String
    var onColorExtracted: (Color) -> Void

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
            if let cached = await ImageCache.shared.cachedImage(for: url, maxPixelSize: 320) {
                image = cached
                extractColor(from: cached)
                return
            }
            if let loaded = await ImageCache.shared.loadImage(from: url, maxPixelSize: 320) {
                image = loaded
                extractColor(from: loaded)
            }
        }
    }

    private func extractColor(from img: CGImage) {
        Task {
            if let color = await EraColorExtractor.shared.extractColor(fromImage: img, cacheKey: cacheKey) {
                await MainActor.run { onColorExtracted(color) }
            }
        }
    }
}
