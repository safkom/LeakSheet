import SwiftUI

/// Leaf views for the artist screen: the flattened era/song/version
/// row, the filter chip, and the notice banner.
///
/// Split out of ArtistView.swift (2026-07-25); behaviour unchanged.

// MARK: - Era row (flattened list)

/// Renders ONE row of the flattened era list. The body wraps its switch in a
/// single-root container so the row is unary — LazyVStack can template row
/// identity from the ForEach ids without evaluating every row's body.
struct EraRowView: View {
    let row: EraRow
    let displayColors: EraDisplayColors?
    let artistName: String
    let artistSlug: String
    let sourceUrl: String?
    let onCardTap: (String) -> Void
    let onColorExtracted: (String, Color) -> Void
    let onSongTap: (Song, String, String?, Int) -> Void
    let onPlayVersion: (SongVersion, String) -> Void
    let onShowDescription: (DescriptionSheet.Payload) -> Void

    var body: some View {
        VStack(spacing: 0) {
            switch row {
            case .card(let filtered, let expanded):
                EraCardView(
                    era: filtered.era,
                    expanded: expanded,
                    displayColors: displayColors,
                    onTap: { onCardTap(filtered.era.name) },
                    onColorExtracted: { color in onColorExtracted(filtered.era.name, color) }
                )
                .padding(.horizontal, 16)

            case .divider:
                Rectangle()
                    .fill(displayColors?.dominant ?? Color.lsAccent)
                    .frame(height: 2)
                    .padding(.horizontal, 16)

            case .groupHeader(let text, _):
                panel(isLast: false) {
                    Text(text)
                        .font(.footnote.weight(.bold))
                        .foregroundStyle(.secondary)
                        .textCase(.uppercase)
                        .padding(.top, 14)
                        .padding(.horizontal, 12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

            case .sectionHeader(let name, _, let group):
                panel(isLast: false) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(name)
                            .font(.subheadline.weight(.semibold))
                            // readableHeader, not dominant: the raw median-cut
                            // colour of a dark cover lands near-black on the
                            // black background, so sub-era headers rendered
                            // invisible. EraDisplayColors already guarantees
                            // contrast — this was the one text site not using it.
                            .foregroundStyle(displayColors?.readableHeader ?? .secondary)
                            .textCase(.uppercase)
                            .tracking(0.5)
                            .padding(.horizontal, 12)
                            .frame(maxWidth: .infinity, alignment: .leading)

                        Rectangle()
                            .fill((displayColors?.dominant ?? Color.lsBorder).opacity(0.3))
                            .frame(height: 1)
                            .padding(.horizontal, 12)
                    }
                    .padding(.top, group == nil ? 14 : 6)
                }

            case .song(let song, let eraName, let eraArt, _, _, let isLast, let ordinal):
                panel(isLast: isLast) {
                    SongRowView(
                        song: song,
                        // bestPlayableVersion, not versions.first and not
                        // bestVersion: the row renders this version's badges
                        // AND acts on it, so the two must agree. versions.first
                        // made a row reading "Lossless · OG File" play the Low
                        // Quality snippet; plain bestVersion ignores whether a
                        // version has a link, which on 457 corpus songs picked
                        // an unplayable one and removed the play affordance
                        // while playable siblings sat underneath.
                        version: song.bestPlayableVersion ?? song.versions.first,
                        artistName: artistName,
                        artistSlug: artistSlug,
                        sourceUrl: sourceUrl,
                        eraName: eraName,
                        eraArt: eraArt,
                        onPlay: { onPlayVersion($0, eraName) },
                        onShowDescription: onShowDescription
                    )
                    .contentShape(Rectangle())
                    .accessibilityAddTraits(.isButton)
                    .onTapGesture {
                        onSongTap(song, eraName, eraArt, ordinal)
                    }
                }

            case .version(let version, let index, let song, let eraName, let eraArt, let isLast, _):
                panel(isLast: isLast) {
                    VersionRowView(
                        version: version,
                        versionIndex: index,
                        song: song,
                        artistName: artistName,
                        artistSlug: artistSlug,
                        sourceUrl: sourceUrl,
                        eraName: eraName,
                        eraArt: eraArt,
                        onPlay: { onPlayVersion($0, eraName) },
                        onShowDescription: onShowDescription
                    )
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }

            case .eraGap:
                Color.clear.frame(height: 12)
            }
        }
    }

    /// Shared with the search / recents / content-tab lists — see SongPanel.
    private func panel<Content: View>(isLast: Bool, @ViewBuilder content: () -> Content) -> some View {
        content().songPanel(displayColors, isLast: isLast)
    }
}

extension EraRow {
    var eraName: String {
        switch self {
        case .card(let filtered, _): return filtered.era.name
        case .divider(let era), .eraGap(let era): return era
        case .groupHeader(_, let era): return era
        case .sectionHeader(_, let era, _): return era
        case .song(_, let era, _, _, _, _, _): return era
        case .version(_, _, _, let era, _, _, _): return era
        }
    }
}

// MARK: - Filter chip

struct FilterChip: View {
    let label: String
    let icon: String
    let isActive: Bool
    var tintColor: Color = .lsAccent
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            Label(label, systemImage: icon)
                .font(.subheadline.weight(.medium))
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .foregroundStyle(isActive ? AnyShapeStyle(Color.preferredText(on: tintColor)) : AnyShapeStyle(.secondary))
                // Tint via opacity — see DECISIONS.md::ArtistRowViews.swift::glass-tint-opacity
                .glassEffect(.regular.tint(tintColor.opacity(isActive ? 1 : 0)).interactive())
        }
        .buttonStyle(.plain)
        .frame(minHeight: Metrics.chipHeight)
        .contentShape(Capsule())
        .accessibilityAddTraits(isActive ? [.isSelected] : [])
    }
}

// MARK: - Notice banner

struct NoticeBannerView: View {
    let notice: Notice
    /// Parent owns the presentation (in-app Safari sheet).
    var onOpenLink: (URL) -> Void

    private var isAlert: Bool { notice.isAlert }
    private var tintColor: Color { isAlert ? .orange : Color(hex: 0x94A3B8) }
    private var bgColor: Color { isAlert ? Color.orange.opacity(0.10) : Color(hex: 0x94A3B8).opacity(0.12) }

    var body: some View {
        Button {
            if let link = notice.link, let url = URL(string: link) {
                onOpenLink(url)
            }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: isAlert ? "exclamationmark.triangle.fill" : "info.circle.fill")
                    .foregroundStyle(tintColor)
                Text(notice.text)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.leading)
                Spacer()
                if notice.link != nil {
                    Image(systemName: "arrow.up.right")
                        .font(.caption2)
                        .foregroundStyle(tintColor.opacity(0.7))
                }
            }
            .padding(12)
            .background(bgColor)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
        .disabled(notice.link == nil)
    }
}
