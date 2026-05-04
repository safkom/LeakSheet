import SwiftUI

/// Convenience alias used throughout the app.
typealias DescriptionSheet = SongDescriptionSheet

/// Sheet showing detailed song/version information — mirrors the web SongDescriptionModal.
struct SongDescriptionSheet: View {
    let payload: Payload

    struct Payload: Identifiable {
        let id = UUID()
        let song: Song?
        let version: SongVersion
        let artistName: String
        let artistSlug: String?
        let eraName: String
        let eraArt: String?
    }

    @Environment(\.dismiss) private var dismiss
    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites

    @State private var accentColor: Color?

    private var badgeInfo: (emoji: String, label: String)? {
        guard let b = payload.version.badge, let badge = Badge(rawValue: b) else { return nil }
        switch badge {
        case .best: return ("⭐", "Best Of")
        case .special: return ("✨", "Special")
        case .worst: return ("🗑️", "Worst Of")
        case .grail: return ("🏆", "Grail")
        case .wanted: return ("🏅", "Wanted")
        case .ai: return ("🤖", "AI")
        }
    }

    private var displayName: String {
        let n = payload.version.name
        // Strip version tag suffix like " [V1]" for cleaner display
        if let tag = payload.version.versionTag, n.hasSuffix(" [\(tag)]") {
            return String(n.dropLast(tag.count + 3))
        }
        return n
    }

    private var subtitle: String? {
        payload.version.altTitles?.first
    }

    private var canStream: Bool {
        payload.version.isStreamable
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        // Prominent album art with gradient
                        VStack(spacing: 12) {
                            if let artUrl = payload.eraArt, let url = APIClient.shared.imageProxyURL(for: artUrl) {
                                CachedImage(url: url) {
                                    Image(systemName: "music.note")
                                        .font(.largeTitle)
                                        .foregroundStyle(.secondary)
                                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                                        .background(Color.lsCard)
                                }
                                .frame(width: 160, height: 160)
                                .clipShape(RoundedRectangle(cornerRadius: 12))
                                .shadow(color: (accentColor ?? .clear).opacity(0.4), radius: 20, y: 8)
                                .task {
                                    accentColor = await EraColorExtractor.shared.extractColor(from: url, eraName: payload.eraName)
                                }
                            }

                            // Era name pill badge
                            HStack(spacing: 6) {
                                Text(payload.eraName.uppercased())
                                    .font(.caption2.weight(.bold))
                                    .tracking(0.8)
                                    .foregroundStyle((accentColor ?? .lsAccent).ensureReadable(against: .lsBackground))
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 4)
                                    .background((accentColor ?? .lsAccent).opacity(0.15))
                                    .clipShape(Capsule())

                                if let badge = badgeInfo {
                                    Text("\(badge.emoji) \(badge.label)")
                                        .font(.caption2.weight(.bold))
                                        .foregroundStyle(.secondary)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 4)
                                        .background(Color.lsCard)
                                        .clipShape(Capsule())
                                }
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)

                        // Title
                        VStack(alignment: .leading, spacing: 2) {
                            Text(displayName)
                                .font(.title.weight(.bold))
                                .foregroundStyle((accentColor ?? .primary).ensureReadable(against: .lsBackground))
                            if let sub = subtitle {
                                Text(sub)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            Text(payload.artistName)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }

                        // Credits section
                        creditsSection

                        // Status badges (quality + availability) — prominent
                        if payload.version.quality != nil || payload.version.availableLength != nil {
                            FlowLayout(spacing: 6) {
                                if let q = payload.version.quality, !q.isEmpty {
                                    let variant = qualityVariant(q)
                                    badgePill(text: q, variant: variant)
                                }
                                if let a = payload.version.availableLength, !a.isEmpty {
                                    let variant = availabilityVariant(a)
                                    badgePill(text: a, variant: variant)
                                }
                            }
                        }

                        // Detail grid (2-column)
                        detailGrid

                        // Alt titles (remaining, after subtitle)
                        if let alts = payload.version.altTitles, alts.count > 1 {
                            cardSection(title: "Alt Titles") {
                                ForEach(alts.dropFirst(), id: \.self) { alt in
                                    Text(alt)
                                        .font(.subheadline)
                                        .foregroundStyle(.primary)
                                }
                            }
                        }

                        // Samples
                        if let samples = payload.version.samples, !samples.isEmpty {
                            cardSection(title: "Samples") {
                                ForEach(samples, id: \.self) { sample in
                                    Text(sample.trimmingCharacters(in: CharacterSet(charactersIn: "\"")))
                                        .font(.subheadline)
                                        .foregroundStyle(.primary)
                                }
                            }
                        }

                        // Notes
                        if let notes = payload.version.notes, !notes.isEmpty {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Notes")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Text(notes)
                                    .font(.subheadline)
                                    .foregroundStyle(.primary)
                                    .padding(12)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(Color.lsCard)
                                    .clipShape(RoundedRectangle(cornerRadius: 8))
                            }
                        }

                        // Links
                        if let links = payload.version.links, !links.isEmpty {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Links")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                ForEach(links, id: \.self) { link in
                                    if let url = URL(string: link) {
                                        Link(destination: url) {
                                            HStack(spacing: 6) {
                                                Image(systemName: "link")
                                                    .font(.caption2)
                                                Text(linkDomain(link))
                                                    .font(.caption)
                                            }
                                            .foregroundStyle(Color.lsAccent)
                                            .padding(.horizontal, 10)
                                            .padding(.vertical, 6)
                                            .background(Color.lsAccent.opacity(0.1))
                                            .clipShape(Capsule())
                                        }
                                    }
                                }
                            }
                        }
                    }
                    .padding(20)
                }

                // Sticky bottom buttons (Play + Favourite)
                HStack(spacing: 12) {
                    if canStream {
                        Button {
                            Haptics.light()
                            player.playTrack(payload.version, artistName: payload.artistName, eraName: payload.eraName, artUrl: payload.eraArt ?? "")
                            dismiss()
                        } label: {
                            Label("Play", systemImage: "play.fill")
                                .font(.headline)
                                .foregroundStyle(.white)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(accentColor ?? Color.lsAccent)
                                .clipShape(RoundedRectangle(cornerRadius: 14))
                        }
                        .buttonStyle(.plain)
                    }

                    // Favourite button — always available
                    Button {
                        Haptics.light()
                        if let song = payload.song, let slug = payload.artistSlug {
                            favourites.toggle(
                                song: song,
                                artistSlug: slug,
                                artistName: payload.artistName,
                                sourceUrl: nil,
                                eraName: payload.eraName,
                                eraArt: payload.eraArt
                            )
                        } else {
                            let slug = payload.artistSlug ?? payload.artistName.slugified
                            favourites.toggleFromVersion(
                                version: payload.version,
                                artistSlug: slug,
                                artistName: payload.artistName,
                                sourceUrl: nil,
                                eraName: payload.eraName,
                                eraArt: payload.eraArt
                            )
                        }
                    } label: {
                        let slug = payload.artistSlug ?? payload.artistName.slugified
                        let isFav = favourites.isFavouritedByVersion(payload.version, artistSlug: slug, eraName: payload.eraName)
                        Image(systemName: isFav ? "heart.fill" : "heart")
                            .font(.headline)
                            .foregroundStyle(isFav ? Color.lsFavourite : .primary)
                            .frame(width: 52, height: 52)
                            .background(Color.lsCard)
                            .clipShape(RoundedRectangle(cornerRadius: 14))
                            .accessibilityLabel(isFav ? "Remove from favourites" : "Add to favourites")
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 12)
            }
            .background(
                ZStack {
                    Color.lsBackground
                    if let accent = accentColor {
                        LinearGradient(
                            colors: [accent.opacity(0.15), Color.clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    }
                }
                .ignoresSafeArea()
            )
            .navigationTitle("Description")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        if canStream {
                            Button {
                                Haptics.light()
                                player.playTrack(payload.version, artistName: payload.artistName, eraName: payload.eraName, artUrl: payload.eraArt ?? "")
                            } label: {
                                Label("Play", systemImage: "play.fill")
                            }
                            Button {
                                player.addToQueue(payload.version, artistName: payload.artistName, eraName: payload.eraName, artUrl: payload.eraArt ?? "")
                                Haptics.light()
                            } label: {
                                Label("Add to Queue", systemImage: "text.append")
                            }
                        }
                        if let song = payload.song, let slug = payload.artistSlug {
                            Button {
                                favourites.toggle(
                                    song: song,
                                    artistSlug: slug,
                                    artistName: payload.artistName,
                                    sourceUrl: nil,
                                    eraName: payload.eraName,
                                    eraArt: payload.eraArt
                                )
                                Haptics.light()
                            } label: {
                                Label("Favourite", systemImage: "heart")
                            }
                        } else {
                            Button {
                                let slug = payload.artistSlug ?? payload.artistName.slugified
                                favourites.toggleFromVersion(
                                    version: payload.version,
                                    artistSlug: slug,
                                    artistName: payload.artistName,
                                    sourceUrl: nil,
                                    eraName: payload.eraName,
                                    eraArt: payload.eraArt
                                )
                                Haptics.light()
                            } label: {
                                Label("Favourite", systemImage: "heart")
                            }
                        }
                        if let link = payload.version.links?.first {
                            Button {
                                UIPasteboard.general.string = link
                            } label: {
                                Label("Copy Link", systemImage: "doc.on.doc")
                            }
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationBackground(.ultraThinMaterial)
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
    }

    // MARK: - Credits section

    @ViewBuilder
    private var creditsSection: some View {
        let credits: [(String, String)] = [
            ("feat.", payload.version.featuring),
            ("prod.", payload.version.producers),
            ("with", payload.version.collaboration),
            ("ref.", payload.version.refs),
        ].compactMap { label, val in
            guard let v = val, !v.isEmpty else { return nil }
            return (label, v)
        }

        if !credits.isEmpty {
            FlowLayout(spacing: 6) {
                ForEach(credits, id: \.0) { label, value in
                    HStack(spacing: 3) {
                        Text(label)
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.tertiary)
                        Text(value)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.lsCard)
                    .clipShape(Capsule())
                }
            }
        }
    }

    // MARK: - Detail grid

    @ViewBuilder
    private var detailGrid: some View {
        let items: [(String, String)] = [
            ("Version", payload.version.versionTag),
            ("Duration", payload.version.trackLength),
            ("File Date", payload.version.fileDate),
            ("Leak Date", payload.version.leakDate),
            ("Type", payload.version.type),
            ("Recording", payload.version.dateOfRecording),
            ("OG Filename", payload.version.ogFilename),
        ].compactMap { label, val in
            guard let v = val, !v.isEmpty else { return nil }
            return (label, v)
        }

        if !items.isEmpty {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 10) {
                ForEach(items, id: \.0) { label, value in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(label)
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.tertiary)
                        Text(value)
                            .font(.subheadline)
                            .foregroundStyle(.primary)
                    }
                }
            }
            .padding(12)
            .background(Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 10))
        }
    }

    // MARK: - Helpers

    private func badgePill(text: String, variant: BadgeVariant) -> some View {
        Text(text)
            .font(.footnote.weight(.semibold))
            .foregroundStyle(variant.foreground)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(variant.background)
            .clipShape(Capsule())
    }

    @ViewBuilder
    private func cardSection<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            content()
        }
    }

    private func linkDomain(_ urlString: String) -> String {
        guard let url = URL(string: urlString), let host = url.host else { return urlString }
        return host.replacingOccurrences(of: "www.", with: "")
    }
}

// MARK: - Flow Layout (wrapping HStack)

struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    struct Cache {
        var width: CGFloat = .nan
        var offsets: [CGPoint] = []
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
            subviews[index].place(at: CGPoint(x: bounds.minX + offset.x, y: bounds.minY + offset.y), proposal: .unspecified)
        }
    }

    private func ensureLayout(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> Cache {
        let width = proposal.width ?? .infinity
        if cache.width == width, cache.offsets.count == subviews.count {
            return cache
        }
        let result = layout(proposal: proposal, subviews: subviews)
        cache = Cache(width: width, offsets: result.offsets, size: result.size)
        return cache
    }

    private func layout(proposal: ProposedViewSize, subviews: Subviews) -> (offsets: [CGPoint], size: CGSize) {
        let maxWidth = proposal.width ?? .infinity
        var offsets: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var maxX: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            offsets.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            maxX = max(maxX, x - spacing)
        }

        // Clamp reported width to the available space so parent containers
        // (especially LazyVStack) don't receive an inflated size when a single
        // child is wider than the proposal (e.g. a very long credit tag).
        let clampedWidth = maxWidth < .infinity ? min(maxX, maxWidth) : maxX
        return (offsets, CGSize(width: clampedWidth, height: y + rowHeight))
    }
}
