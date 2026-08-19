import SwiftUI

/// Row for one Misc / Music Videos entry — thumbnail (when the content is an
/// image or video), name, type capsule, metadata, and a per-link affordance.
/// Misc entries are separate from the era/song tree, so this row doesn't
/// reuse SongRowView (which requires a Song).
///
/// The Link(s) column mixes audio streams, images, videos, and zip/archive
/// downloads with no structured type — `MiscEntry.mediaLinks` classifies each
/// one so the trailing control matches what tapping it actually does: a
/// single link gets one plain icon (the row's own tap performs it directly),
/// multiple links get a menu labeled by kind and host so choosing one is
/// never a guess.
struct MiscEntryRowView: View {
    let entry: MiscEntry
    var onShowDescription: (DescriptionSheet.Payload) -> Void
    var onSelectLink: (MiscLink) -> Void

    /// Computed ONCE per row, not per access. `entry.mediaLinks` is a computed
    /// property that runs MiscLinkClassifier.classify (a URLComponents parse
    /// plus a StreamResolver.target parse) and label(for:) per link — and this
    /// view read it five times per body evaluation, on a tab that can carry
    /// ~1900 entries.
    private let links: [MiscLink]
    private let previewURL: URL?

    init(
        entry: MiscEntry,
        onShowDescription: @escaping (DescriptionSheet.Payload) -> Void,
        onSelectLink: @escaping (MiscLink) -> Void
    ) {
        self.entry = entry
        self.onShowDescription = onShowDescription
        self.onSelectLink = onSelectLink
        self.links = entry.mediaLinks
        self.previewURL = entry.previewImageURL.flatMap(URL.init(string:))
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            if let previewURL {
                thumbnail(url: previewURL)
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(entry.name)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.primary)
                    .lineLimit(2)

                // FlowLayout so type/quality/availability pills wrap instead of
                // clipping at accessibility Dynamic Type.
                FlowLayout(spacing: 5) {
                    if let type = entry.entryType, !type.isEmpty {
                        typePill(type)
                    }
                    if let primary = BadgeLogic.primaryPill(quality: entry.quality, availability: entry.available) {
                        BadgePill(
                            text: primary.text,
                            variant: primary.isQuality
                                ? qualityVariant(primary.text)
                                : availabilityVariant(primary.text),
                            accessibilityPrefix: primary.isQuality ? "Quality" : "Availability"
                        )
                    }
                    if let avail = BadgeLogic.availabilityPill(quality: entry.quality, availability: entry.available) {
                        BadgePill(text: avail.text, variant: availabilityVariant(avail.text), accessibilityPrefix: "Availability")
                    }
                }

                HStack(spacing: 6) {
                    if let date = entry.date, !date.isEmpty, date.lowercased() != "n/a" {
                        metaText(date, icon: "calendar")
                    }
                    if let length = entry.length, !length.isEmpty, length.lowercased() != "n/a" {
                        metaText(length, icon: "clock")
                    }
                    if entry.streaming == true {
                        metaText("Streaming", icon: "antenna.radiowaves.left.and.right")
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            trailingAffordance
        }
        // Matches SongRowView's metrics so a content-tab row reads as the same
        // kind of object as a song row. These used to be 6pt vertical, no
        // horizontal padding, no clip and no hover — visibly a different row
        // family sitting under the same era card.
        .padding(.vertical, Metrics.rowVerticalPadding)
        .padding(.horizontal, Metrics.rowHorizontalPadding)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .rowHoverHighlight()
        .accessibilityElement(children: .combine)
    }

    // MARK: - Thumbnail

    /// Through the proxy like every other CachedImage call site: the raw
    /// third-party URL meant no backend downscale (a 1280px YouTube thumbnail
    /// decoded for a 44pt cell), no 429/Retry-After handling, and exposure to
    /// hotlink blocking.
    private func thumbnail(url: URL) -> some View {
        CachedImage(
            url: APIClient.shared.imageProxyURL(for: url.absoluteString, width: 128) ?? url,
            maxPixelSize: 128
        ) {
            ArtworkPlaceholder(cornerRadius: 6)
        }
        .frame(width: 44, height: 44)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .overlay(alignment: .bottomTrailing) {
            // Video thumbnails come from a still frame — badge them so it
            // reads as playable, not just a photo.
            if links.contains(where: { $0.kind == .video }) {
                Image(systemName: "play.fill")
                    .font(.system(size: 8))
                    .foregroundStyle(.white)
                    .padding(3)
                    .background(.black.opacity(0.55), in: Circle())
                    .padding(2)
            }
        }
        .accessibilityHidden(true)
    }

    // MARK: - Trailing affordance

    /// One plain icon when there's a single link (the row's own tap already
    /// performs it); a labeled menu when there's more than one, so picking
    /// among a stream/archive/video/link never has to be a guess.
    @ViewBuilder
    private var trailingAffordance: some View {
        switch links.count {
        case 0:
            EmptyView()
        case 1:
            Image(systemName: links[0].kind.systemImage)
                .font(.body)
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
        default:
            Menu {
                ForEach(links) { link in
                    Button {
                        onSelectLink(link)
                    } label: {
                        Label(link.label, systemImage: link.kind.systemImage)
                    }
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel("Choose link")
        }
    }

    // MARK: - Pieces

    /// The shared pill, not a fifth bespoke copy — BadgePill's own doc comment
    /// already claims to have folded every one of these in.
    private func typePill(_ type: String) -> some View {
        BadgePill(text: type.uppercased(), variant: .accent, accessibilityPrefix: "Type")
    }

    private func metaText(_ text: String, icon: String) -> some View {
        HStack(spacing: 3) {
            Image(systemName: icon)
                .font(.caption2)
            Text(text)
                .font(.caption2)
        }
        .foregroundStyle(.secondary)
    }
}
