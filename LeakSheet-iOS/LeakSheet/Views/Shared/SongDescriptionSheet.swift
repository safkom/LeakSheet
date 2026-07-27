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
    /// In-app Safari for version links + evidence — the sheet must never
    /// bounce the user out to system Safari.
    @State private var safariItem: SafariItem?
    /// Present when the sheet is shown from the artist screen — powers the
    /// cross-era "Also in" section. Nil from Now Playing / Favourites.
    @Environment(ArtistViewModel.self) private var artistVM: ArtistViewModel?

    private var badgeInfo: (emoji: String, label: String)? {
        guard let b = payload.version.badge, let badge = Badge(rawValue: b) else { return nil }
        return (badge.emoji, badge.label)
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

    /// Play the sheet's version. When the full song is known, hand the player
    /// the song's streamable versions as a list so playback continues instead
    /// of stopping after this one track.
    private func play() {
        Haptics.light()
        if let song = payload.song {
            let streamable = song.versions.filter(\.isStreamable)
            if let idx = streamable.firstIndex(where: { $0.id == payload.version.id }) {
                let items = streamable.map {
                    PlaybackListItem(
                        version: $0,
                        artistName: payload.artistName,
                        eraName: payload.eraName,
                        artUrl: payload.eraArt ?? "",
                        artistSlug: payload.artistSlug
                    )
                }
                player.playInList(items, startAt: idx)
                return
            }
        }
        player.playTrack(payload.version, artistName: payload.artistName, eraName: payload.eraName, artUrl: payload.eraArt ?? "", artistSlug: payload.artistSlug ?? "")
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        // Prominent album art with gradient
                        VStack(spacing: 12) {
                            if let artUrl = payload.eraArt, let url = APIClient.shared.imageProxyURL(for: artUrl, width: 640) {
                                CachedImage(url: url, maxPixelSize: 640) {
                                    ArtworkPlaceholder(cornerRadius: 0)
                                        .font(.largeTitle)
                                }
                                .frame(width: 160, height: 160)
                                .clipShape(RoundedRectangle(cornerRadius: 12))
                                .shadow(color: (accentColor ?? .clear).opacity(0.4), radius: 20, y: 8)
                                .task {
                                    accentColor = await EraColorExtractor.shared.extractColor(from: url, cacheKey: artUrl)
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

                        // Status badges (quality + availability + fan rating) — prominent
                        if payload.version.quality != nil || payload.version.availableLength != nil || payload.version.rating != nil {
                            FlowLayout(spacing: 6) {
                                // Same dedupe rules as the song rows (SPEC §12),
                                // rendered at this sheet's larger pill size.
                                if let primary = BadgeLogic.primaryPill(
                                    quality: payload.version.quality,
                                    availability: payload.version.availableLength
                                ) {
                                    badgePill(
                                        text: primary.text,
                                        variant: primary.isQuality
                                            ? qualityVariant(primary.text)
                                            : availabilityVariant(primary.text)
                                    )
                                }
                                if let avail = BadgeLogic.availabilityPill(
                                    quality: payload.version.quality,
                                    availability: payload.version.availableLength
                                ) {
                                    badgePill(text: avail.text, variant: availabilityVariant(avail.text))
                                }
                                if let rating = payload.version.rating {
                                    ratingPill(rating)
                                }
                            }
                        }

                        // Detail grid (2-column)
                        detailGrid

                        // Stream file info (codec, bitrate, …) — provider
                        // metadata API with live-player fallback.
                        if payload.version.streamableLink != nil {
                            FileInfoSection(version: payload.version)
                        }

                        // Story — the tracker's notes are the main learning
                        // content; they read directly after the facts.
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

                        // OG file(s) — dedicated section, pluralized by count
                        let ogFiles = payload.version.allOgFilenames
                        if !ogFiles.isEmpty {
                            cardSection(title: ogFiles.count == 1 ? "OG File" : "OG Files") {
                                ForEach(ogFiles, id: \.self) { file in
                                    Text(file)
                                        .font(.subheadline.monospaced())
                                        .foregroundStyle(.primary)
                                }
                            }
                        }

                        // Samples
                        if let samples = payload.version.samples, !samples.isEmpty {
                            cardSection(title: "Samples") {
                                ForEach(samples, id: \.self) { sample in
                                    Text(sample)
                                        .font(.subheadline)
                                        .foregroundStyle(.primary)
                                }
                            }
                        }

                        // Evidence — labeled provenance links from the
                        // tracker's Sources column ('First Mention
                        // (Screenshot)', 'Trailer (YouTube)').
                        if let sources = payload.version.sources, !sources.isEmpty {
                            EvidenceSection(sources: sources) { url in
                                safariItem = SafariItem(url: url)
                            }
                        }

                        // Links — filter to valid URLs first so the header
                        // never renders above an empty list.
                        let validLinks = (payload.version.links ?? []).compactMap { link in
                            URL(string: link).map { (raw: link, url: $0) }
                        }
                        if !validLinks.isEmpty {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Links")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                ForEach(validLinks, id: \.raw) { link in
                                    Button {
                                        safariItem = SafariItem(url: link.url)
                                    } label: {
                                        HStack(spacing: 6) {
                                            Image(systemName: "link")
                                                .font(.caption2)
                                            Text(Format.shortHost(link.raw))
                                                .font(.caption)
                                        }
                                        .foregroundStyle(Color.lsAccent)
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 6)
                                        .background(Color.lsAccent.opacity(0.1))
                                        .clipShape(Capsule())
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }

                        // Cross-era linkage: other eras carrying the same
                        // song (matched by the parser's normalized song_key).
                        if let vm = artistVM {
                            let alsoIn = vm.otherEras(
                                forSongKey: payload.song?.songKey,
                                excluding: payload.eraName
                            )
                            if !alsoIn.isEmpty {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text("Also in")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.secondary)
                                    ForEach(alsoIn) { ref in
                                        HStack(spacing: 6) {
                                            Image(systemName: "square.stack")
                                                .font(.caption2)
                                            Text(ref.eraName)
                                                .font(.caption)
                                            Spacer(minLength: 0)
                                            Text("\(ref.versionCount) version\(ref.versionCount == 1 ? "" : "s")")
                                                .font(.caption2)
                                                .foregroundStyle(.secondary)
                                        }
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 8)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .background(Color.lsCard)
                                        .clipShape(RoundedRectangle(cornerRadius: 8))
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
                            play()
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
            .toolbarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        if canStream {
                            Button {
                                play()
                            } label: {
                                Label("Play", systemImage: "play.fill")
                            }
                            Button {
                                player.addToQueue(payload.version, artistName: payload.artistName, eraName: payload.eraName, artUrl: payload.eraArt ?? "", artistSlug: payload.artistSlug ?? "")
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
                    .accessibilityLabel("More options")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationBackground(.ultraThinMaterial)
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
    }

    // MARK: - Credits section

    @ViewBuilder
    private var creditsSection: some View {
        let credits: [(String, String)] = [
            ("feat.", payload.version.featuring),
            ("prod.", payload.version.producers),
            ("with", payload.version.collaboration),
            ("ref.", payload.version.refs),
            ("artist", payload.version.creditedArtists),
        ].compactMap { label, val in
            guard let v = val, !v.isEmpty else { return nil }
            return (label, v)
        }

        if !credits.isEmpty {
            FlowLayout(spacing: 6) {
                ForEach(credits, id: \.0) { label, value in
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(label)
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.tertiary)
                        Text(value)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            // Allow the value to wrap to multiple lines when the
                            // pill is width-constrained (long producer lists),
                            // instead of forcing a single line that overflows.
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.lsCard)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
        }
    }

    // MARK: - Detail grid

    @ViewBuilder
    private var detailGrid: some View {
        // Date cells are shown verbatim, digits or not: trackers legitimately
        // write "Spring", "Late 2004 sessions", "Ooc" — the web reference
        // renders them, and hiding them silently loses tracker information.
        let items: [(String, String)] = [
            ("Version", payload.version.versionTag),
            ("Duration", payload.version.trackLength),
            ("File Date", payload.version.fileDate),
            ("Leak Date", payload.version.leakDate),
            ("Type", payload.version.type),
            ("Recording", payload.version.dateOfRecording),
        ].compactMap { label, val in
            guard let v = val?.trimmingCharacters(in: .whitespaces), !v.isEmpty else { return nil }
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

    /// Fan star rating (1-5) from the tracker's availability cell.
    private func ratingPill(_ rating: Int) -> some View {
        HStack(spacing: 2) {
            ForEach(1...5, id: \.self) { star in
                Image(systemName: star <= rating ? "star.fill" : "star")
                    .font(.caption2)
                    .foregroundStyle(star <= rating ? Color.yellow : Color.lsDim)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Color.lsCard)
        .clipShape(Capsule())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Fan rating \(rating) of 5 stars")
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

}
