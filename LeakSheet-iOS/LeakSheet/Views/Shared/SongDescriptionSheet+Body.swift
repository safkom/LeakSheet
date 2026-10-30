import SwiftUI

extension SongDescriptionSheet {
    @ViewBuilder
    var artHeader: some View {
        // Prominent album art with gradient
        VStack(spacing: 12) {
            if let artUrl = active.eraArt, let url = APIClient.shared.imageProxyURL(
                for: artUrl,
                width: 640
            ) {
                CachedImage(url: url, maxPixelSize: 640) {
                    ArtworkPlaceholder(cornerRadius: 0)
                        .font(.largeTitle)
                }
                .frame(width: 160, height: 160)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .shadow(color: (accentColor ?? .clear).opacity(0.4), radius: 20, y: 8)
                // Keyed on artUrl: picking a version from a
                // different era swaps the art, so the extracted
                // accent has to be re-run, not just the image.
                .task(id: artUrl) {
                    accentColor = await EraColorExtractor.shared.extractColor(
                        from: url,
                        cacheKey: artUrl
                    )
                }
            }

            // Era name pill badge
            HStack(spacing: 6) {
                Text(active.eraName.uppercased())
                    .font(.caption2.weight(.bold))
                    .tracking(0.8)
                    .foregroundStyle((accentColor ?? .lsAccent).ensureReadable(
                        against: .lsBackground,
                        in: colorScheme
                    ))
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
    }

    @ViewBuilder
    var titleBlock: some View {
        // Title
        VStack(alignment: .leading, spacing: 2) {
            Text(displayName)
                .font(.title.weight(.bold))
                // .white, not .primary: a dynamic colour resolves to black in the
                // contrast maths, greying the title until the artwork task lands.
                .foregroundStyle((accentColor ?? .white).ensureReadable(
                    against: .lsBackground,
                    in: colorScheme
                ))
            if let sub = subtitle {
                Text(sub)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Text(payload.artistName)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    var statusBadges: some View {
        // Status badges (quality + availability + fan rating) — prominent
        if active.version.quality != nil || active.version.availableLength != nil
            || active.version.rating != nil {
            FlowLayout(spacing: 6) {
                // Same dedupe rules as the song rows (SPEC §12),
                // rendered at this sheet's larger pill size.
                if let primary = BadgeLogic.primaryPill(
                    quality: active.version.quality,
                    availability: active.version.availableLength
                ) {
                    BadgePill(
                        text: primary.text,
                        variant: primary.isQuality
                            ? qualityVariant(primary.text)
                            : availabilityVariant(primary.text),
                        prominent: true
                    )
                }
                if let avail = BadgeLogic.availabilityPill(
                    quality: active.version.quality,
                    availability: active.version.availableLength
                ) {
                    BadgePill(
                        text: avail.text,
                        variant: availabilityVariant(avail.text),
                        prominent: true
                    )
                }
                if let rating = active.version.rating {
                    ratingPill(rating)
                }
            }
        }
    }

    @ViewBuilder
    var streamInfo: some View {
        // Stream file info (codec, bitrate, …) — provider
        // metadata API with live-player fallback.
        if active.version.streamableLink != nil {
            FileInfoSection(version: active.version)
        }

        if active.version.streaming == true, !payload.artistName.isEmpty {
            AppleMusicSection(artist: payload.artistName, title: active.version.name)
        }

        if active.version.streamableLinks.count > 1 {
            SourcesSection(
                version: active.version,
                playingLink: player.isNowPlaying(active.version, inEra: active.eraName)
                    ? player.currentTrack?.streamableLink : nil
            ) { link in
                // Stays open so sources can be compared.
                active.version = active.version.playing(link)
                play()
            }
        }
    }

    @ViewBuilder
    var storySections: some View {
        // Story — the tracker's notes are the main learning
        // content; they read directly after the facts.
        if let notes = active.version.notes, !notes.isEmpty {
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
        if let alts = active.version.altTitles, alts.count > 1 {
            CardSection(title: "Alt Titles") {
                ForEach(alts.dropFirst(), id: \.self) { alt in
                    Text(alt)
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                }
            }
        }

        // OG file(s) — dedicated section, pluralized by count
        let ogFiles = active.version.allOgFilenames
        if !ogFiles.isEmpty {
            CardSection(title: ogFiles.count == 1 ? "OG File" : "OG Files") {
                ForEach(ogFiles, id: \.self) { file in
                    Text(file)
                        .font(.subheadline.monospaced())
                        .foregroundStyle(.primary)
                }
            }
        }

        // Samples
        if let samples = active.version.samples, !samples.isEmpty {
            CardSection(title: "Samples") {
                ForEach(samples, id: \.self) { sample in
                    Text(sample)
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                }
            }
        }
    }

    @ViewBuilder
    var linkSections: some View {
        // Evidence — labeled provenance links from the
        // tracker's Sources column ('First Mention
        // (Screenshot)', 'Trailer (YouTube)').
        if let sources = active.version.sources, !sources.isEmpty {
            EvidenceSection(sources: sources) { url in
                safariItem = SafariItem(url: url)
            }
        }

        // Links — filter to valid URLs first so the header
        // never renders above an empty list.
        let validLinks = (active.version.links ?? []).compactMap { link in
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
    }

    @ViewBuilder
    var bottomBar: some View {
        // Sticky bottom buttons (Play + Favourite)
        HStack(spacing: 12) {
            if canStream {
                Button {
                    play()
                    if !embedded { dismiss() }
                } label: {
                    Label("Play", systemImage: "play.fill")
                        .font(.headline)
                        .foregroundStyle(Color.preferredText(on: accentColor ?? .lsAccent, in: colorScheme))
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
                toggleFavourite()
            } label: {
                let slug = payload.artistSlug ?? payload.artistName.slugified
                let isFav = favourites.isFavouritedByVersion(
                    active.version,
                    artistSlug: slug,
                    eraName: active.eraName
                )
                Image(systemName: isFav ? "heart.fill" : "heart")
                    .font(.headline)
                    .foregroundStyle(isFav ? Color.lsFavourite : .primary)
                    .frame(width: 52, height: 52)
                    .background(Color.lsCard)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                    .accessibilityLabel(isFav ? "Remove from favourites" : "Add to favourites")
            }
            .buttonStyle(.plain)

            // Embedded has no toolbar to hang the overflow menu on.
            if embedded {
                Menu { overflowItems } label: {
                    Image(systemName: "ellipsis")
                        .font(.headline)
                        .frame(width: 52, height: 52)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .frame(width: 52)
                .accessibilityLabel("More options")
            }
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 12)
    }
}
