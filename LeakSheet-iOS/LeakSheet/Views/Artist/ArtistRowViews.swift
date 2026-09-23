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

            case .sectionHeader(let name, _, let group, let notes):
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

                        if let notes, !notes.isEmpty {
                            SectionNotesView(notes: notes)
                                .padding(.horizontal, 12)
                        }

                        Rectangle()
                            .fill((displayColors?.dominant ?? Color.lsBorder).opacity(0.3))
                            .frame(height: 1)
                            .padding(.horizontal, 12)
                    }
                    .padding(.top, group == nil ? 14 : 6)
                }

            case .song(let song, let eraName, let eraArt, let expanded, _, let isLast, let ordinal):
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
                        isExpanded: expanded,
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
        case .sectionHeader(_, let era, _, _): return era
        case .song(_, let era, _, _, _, _, _): return era
        case .version(_, _, _, let era, _, _, _): return era
        }
    }
}

// MARK: - Notice banner

/// A tracker's header notices. Alerts ("links are down") keep a full banner;
/// the informational links ("Sheet Link", "Official Discord Server") share
/// one scrolling row of chips instead of a full-width banner each.
struct NoticesView: View {
    let notices: [Notice]
    var onOpenLink: (URL) -> Void

    var body: some View {
        let banners = notices.filter { $0.isAlert || $0.link == nil }
        let links = notices.filter { !$0.isAlert && $0.link != nil }
        VStack(spacing: 4) {
            ForEach(banners) { notice in
                NoticeBannerView(notice: notice, onOpenLink: onOpenLink)
                    .padding(.horizontal, 16)
            }
            if !links.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(links) { notice in
                            Button {
                                if let link = notice.link, let url = URL(string: link) { onOpenLink(url) }
                            } label: {
                                Label(notice.text, systemImage: "arrow.up.right")
                                    .labelStyle(TrailingIconLabelStyle())
                                    .font(.caption.weight(.medium))
                                    .lineLimit(1)
                                    .padding(.horizontal, 12)
                                    .frame(minHeight: Metrics.hitTarget)
                                    .background(Capsule().fill(Color.lsCard))
                            }
                            .buttonStyle(.plain)
                            .accessibilityHint("Opens in the browser")
                        }
                    }
                    .padding(.horizontal, 16)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

private struct TrailingIconLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 4) {
            configuration.title
            configuration.icon.font(.caption2).foregroundStyle(.secondary)
        }
    }
}

struct NoticeBannerView: View {
    let notice: Notice
    /// Parent owns the presentation (in-app Safari sheet).
    var onOpenLink: (URL) -> Void

    private var isAlert: Bool { notice.isAlert }
    private var tintColor: Color { isAlert ? .badgeRec : .secondary }
    private var bgColor: Color { isAlert ? Color.badgeRec.opacity(0.12) : Color.lsCard }

    var body: some View {
        Button {
            if let link = notice.link, let url = URL(string: link) {
                onOpenLink(url)
            }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: isAlert ? "exclamationmark.triangle.fill" : "info.circle.fill")
                    .foregroundStyle(tintColor)
                    .accessibilityHidden(true)
                Text(notice.text)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.leading)
                Spacer()
                if notice.link != nil {
                    Image(systemName: "arrow.up.right")
                        .font(.caption2)
                        .foregroundStyle(tintColor.opacity(0.7))
                        .accessibilityHidden(true)
                }
            }
            .padding(12)
            .background(bgColor)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
        .disabled(notice.link == nil)
        // The kind is carried by an icon a screen reader cannot see, and the
        // arrow that signals "this opens something" is decoration.
        .accessibilityLabel("\(isAlert ? "Alert" : "Notice"): \(notice.text)")
        .accessibilityHint(notice.link == nil ? "" : "Opens in the browser")
    }
}

// MARK: - Section notes

/// A sub-era's own text from the sheet — usually its timeline, written
/// "(06/18/2013) (Yeezus officially releases)" one event per line.
struct SectionNotesView: View {
    let notes: String
    @State private var expanded = false

    private var lines: [String] {
        notes.split(separator: "\n").map { line in
            let parts = line.split(separator: ")", maxSplits: 1)
            guard parts.count == 2, line.hasPrefix("(") else { return String(line) }
            let date = parts[0].dropFirst()
            var event = parts[1].trimmingCharacters(in: .whitespaces)
            if event.hasPrefix("("), event.hasSuffix(")") { event = String(event.dropFirst().dropLast()) }
            return event.isEmpty ? String(date) : "\(date) — \(event)"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(lines.joined(separator: "\n"))
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(expanded ? nil : 2)
            if lines.count > 2 {
                Button(expanded ? "Less" : "More") { expanded.toggle() }
                    .font(.caption.weight(.semibold))
                    .buttonStyle(.plain)
                    .frame(minHeight: Metrics.hitTarget, alignment: .leading)
            }
        }
    }
}
