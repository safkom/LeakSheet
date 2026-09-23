import SwiftUI

/// Convenience alias used throughout the app.
typealias DescriptionSheet = SongDescriptionSheet

/// Sheet showing detailed song/version information.
struct SongDescriptionSheet: View {
    let payload: Payload

    /// Set when hosted as the macOS Details inspector rather than presented as a
    /// sheet: the host supplies the chrome, and there is nothing to dismiss.
    let embedded: Bool

    /// Defined in Shared/Models so FavouritesManager and the tvOS detail screen
    /// can build one without depending on this sheet.
    typealias Payload = SongDetailPayload

    /// The version the sheet shows: `payload.version` until a picker chip is chosen.
    /// Everything below reads `active`, never `payload`, so the whole sheet follows it.
    private struct ActiveVersion {
        var version: SongVersion
        var song: Song?
        var eraName: String
        var eraArt: String?
    }

    @State private var active: ActiveVersion

    init(payload: Payload, embedded: Bool = false) {
        self.payload = payload
        self.embedded = embedded
        _active = State(initialValue: ActiveVersion(
            version: payload.version, song: payload.song,
            eraName: payload.eraName, eraArt: payload.eraArt
        ))
    }

    @Environment(\.dismiss) private var dismiss
    @Environment(PlayerViewModel.self) private var player
    @Environment(FavouritesManager.self) private var favourites
    /// Contrast is judged against the Mac inspector's real system appearance: see
    /// DECISIONS.md::DesignTokens.swift::scheme-parameter.
    @Environment(\.colorScheme) private var colorScheme

    @State private var accentColor: Color?
    /// In-app Safari for version links + evidence — the sheet must never
    /// bounce the user out to system Safari.
    @State private var safariItem: SafariItem?
    /// Present when the sheet is shown from the artist screen — powers the
    /// cross-era version picker. Nil from Now Playing / Favourites, where the
    /// picker falls back to just this song's own versions.
    @Environment(ArtistViewModel.self) private var environmentVM: ArtistViewModel?

    /// The environment's view model only when it describes this payload's artist
    /// (the Favourites sheet gets the *playing* artist's).
    private var artistVM: ArtistViewModel? {
        guard let vm = environmentVM, let slug = payload.artistSlug, vm.artist.slug == slug else { return nil }
        return vm
    }

    /// One version, wherever it lives — its own era if the song is era-unique,
    /// or every era sharing the same `songKey` when it isn't. Falls back to the
    /// current era's own versions when there's no `ArtistViewModel` to ask
    /// (Now Playing / Favourites) or the song has no cross-era duplicates.
    private var pickerVersions: [ArtistViewModel.CrossEraVersion] {
        if let vm = artistVM {
            let refs = vm.crossEraRefs(for: payload)
            if !refs.isEmpty {
                return refs.flatMap { ref in
                    ref.song.allVersions.map {
                        .init(version: $0, song: ref.song, eraName: ref.eraName, eraArt: ref.eraArt)
                    }
                }
            }
            // Era-unique song: songKeyEras drops single-era keys, so recover
            // the unfiltered song by base name rather than trusting the
            // payload's copy, which a badge filter may have truncated.
            if let resolved = vm.resolvedSong(for: payload) {
                return resolved.allVersions.map {
                    .init(version: $0, song: resolved, eraName: payload.eraName, eraArt: payload.eraArt)
                }
            }
        }
        let versions = payload.song?.allVersions ?? [payload.version]
        return versions.map {
            .init(version: $0, song: payload.song, eraName: payload.eraName, eraArt: payload.eraArt)
        }
    }

    /// Versions of songs linked to this one by name — its alt titles, the parts
    /// of a slash title, or another song naming this one (see
    /// ArtistViewModel.linkedRefs). Shown as their own row, apart from this
    /// song's versions, because a link is not a claim that they are one song.
    private var linkedVersions: [ArtistViewModel.CrossEraVersion] {
        guard let vm = artistVM else { return [] }
        return vm.linkedRefs(for: payload).flatMap { ref in
            ref.song.allVersions.map {
                .init(version: $0, song: ref.song, eraName: ref.eraName, eraArt: ref.eraArt)
            }
        }
    }

    private var badgeInfo: (emoji: String, label: String)? {
        guard let b = active.version.badge, let badge = Badge(rawValue: b) else { return nil }
        return (badge.emoji, badge.label)
    }

    private var displayName: String {
        let n = active.version.name
        // Strip version tag suffix like " [V1]" for cleaner display
        if let tag = active.version.versionTag, n.hasSuffix(" [\(tag)]") {
            return String(n.dropLast(tag.count + 3))
        }
        return n
    }

    private var subtitle: String? {
        active.version.altTitles?.first
    }

    private var canStream: Bool {
        active.version.isStreamable
    }

    /// Play the sheet's version. When the full song is known, hand the player
    /// the song's streamable versions as a list so playback continues instead
    /// of stopping after this one track.
    private func play() {
        Haptics.light()
        if let song = active.song {
            // allVersions: a filtered copy would queue only the versions that
            // matched the badge filter, so playback stopped after one track.
            let streamable = song.allVersions.filter(\.isStreamable)
            if let idx = streamable.firstIndex(where: { $0.id == active.version.id }) {
                let items = streamable.map {
                    PlaybackListItem(
                        version: $0,
                        artistName: payload.artistName,
                        eraName: active.eraName,
                        artUrl: active.eraArt ?? "",
                        artistSlug: payload.artistSlug
                    )
                }
                player.playInList(items, startAt: idx)
                return
            }
        }
        player.playTrack(active.version, artistName: payload.artistName, eraName: active.eraName, artUrl: active.eraArt ?? "", artistSlug: payload.artistSlug ?? "")
    }

    var body: some View {
        if embedded {
            content
                .webSheet(item: $safariItem)
        } else {
            NavigationStack {
                content
                    .navigationTitle("Description")
                    #if os(iOS)
                    .toolbarTitleDisplayMode(.inline)
                    #endif
                    .toolbar { chromeToolbar }
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
            .webSheet(item: $safariItem)
        }
    }

    private var content: some View {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        // Prominent album art with gradient
                        VStack(spacing: 12) {
                            if let artUrl = active.eraArt, let url = APIClient.shared.imageProxyURL(for: artUrl, width: 640) {
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
                                    accentColor = await EraColorExtractor.shared.extractColor(from: url, cacheKey: artUrl)
                                }
                            }

                            // Era name pill badge
                            HStack(spacing: 6) {
                                Text(active.eraName.uppercased())
                                    .font(.caption2.weight(.bold))
                                    .tracking(0.8)
                                    .foregroundStyle((accentColor ?? .lsAccent).ensureReadable(against: .lsBackground, in: colorScheme))
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
                                // .white, not .primary: a dynamic colour resolves to black in the
                                // contrast maths, greying the title until the artwork task lands.
                                .foregroundStyle((accentColor ?? .white).ensureReadable(against: .lsBackground, in: colorScheme))
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
                        if active.version.quality != nil || active.version.availableLength != nil || active.version.rating != nil {
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
                                    BadgePill(text: avail.text, variant: availabilityVariant(avail.text), prominent: true)
                                }
                                if let rating = active.version.rating {
                                    ratingPill(rating)
                                }
                            }
                        }

                        // Version picker — every version of this song, across
                        // every era it appears in (fallback: just this era's
                        // versions when the song has no cross-era duplicates).
                        versionPicker

                        // Detail grid (2-column)
                        detailGrid

                        // Stream file info (codec, bitrate, …) — provider
                        // metadata API with live-player fallback.
                        if active.version.streamableLink != nil {
                            FileInfoSection(version: active.version)
                        }

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
                            cardSection(title: "Alt Titles") {
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
                            cardSection(title: ogFiles.count == 1 ? "OG File" : "OG Files") {
                                ForEach(ogFiles, id: \.self) { file in
                                    Text(file)
                                        .font(.subheadline.monospaced())
                                        .foregroundStyle(.primary)
                                }
                            }
                        }

                        // Samples
                        if let samples = active.version.samples, !samples.isEmpty {
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
                    .padding(20)
                }

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
                        let isFav = favourites.isFavouritedByVersion(active.version, artistSlug: slug, eraName: active.eraName)
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
    }

    // MARK: - Chrome

    @ToolbarContentBuilder
    private var chromeToolbar: some ToolbarContent {
        // Actions go trailing, not in the leading slot other sheets use to close;
        // Done is the confirmation.
        ToolbarItem(placement: .primaryAction) {
            Menu {
                overflowItems
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .accessibilityLabel("More options")
        }
        ToolbarItem(placement: .confirmationAction) {
            Button("Done") { dismiss() }
        }
    }

    /// Secondary actions — the toolbar menu when presented, the bottom-bar
    /// menu when embedded.
    @ViewBuilder
    private var overflowItems: some View {
        if canStream {
            Button {
                play()
            } label: {
                Label("Play", systemImage: "play.fill")
            }
            Button {
                player.addToQueue(active.version, artistName: payload.artistName, eraName: active.eraName, artUrl: active.eraArt ?? "", artistSlug: payload.artistSlug ?? "")
                Haptics.light()
            } label: {
                Label("Add to Queue", systemImage: "text.append")
            }
        }
        Button {
            toggleFavourite()
            Haptics.light()
        } label: {
            Label("Favourite", systemImage: "heart")
        }
        if let link = active.version.links?.first {
            Button {
                Pasteboard.copy(link)
            } label: {
                Label("Copy Link", systemImage: "doc.on.doc")
            }
        }
    }

    // MARK: - Version picker

    /// Horizontal chip row of every version of this song, including other eras' (see
    /// `pickerVersions`, read exactly once here: it is a cross-era lookup). A chip
    /// re-points the whole sheet via `active`.
    @ViewBuilder
    private var versionPicker: some View {
        let versions = pickerVersions
        let linked = linkedVersions
        if versions.count > 1 || !linked.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                if versions.count > 1 {
                    chipRow(title: "Versions", entries: versions, showsTitle: false)
                }
                if !linked.isEmpty {
                    chipRow(title: "Also Known As", entries: linked, showsTitle: true)
                }
            }
        }
    }

    /// Opens scrolled to the version the sheet was opened for, so a deep version's
    /// chip isn't off-screen.
    private func chipRow(
        title: String, entries: [ArtistViewModel.CrossEraVersion], showsTitle: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(entries) { entry in
                            versionChip(entry, showsTitle: showsTitle)
                                .id(entry.id)
                        }
                    }
                    .padding(.vertical, 2)
                }
                .onAppear {
                    guard let selected = entries.first(where: isActive) else { return }
                    proxy.scrollTo(selected.id, anchor: .center)
                }
            }
        }
    }

    private func isActive(_ entry: ArtistViewModel.CrossEraVersion) -> Bool {
        entry.version.id == active.version.id && entry.eraName == active.eraName
    }

    private func versionChip(_ entry: ArtistViewModel.CrossEraVersion, showsTitle: Bool) -> some View {
        let isSelected = isActive(entry)
        return Button {
            Haptics.light()
            active = ActiveVersion(
                version: entry.version, song: entry.song,
                eraName: entry.eraName, eraArt: entry.eraArt
            )
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 4) {
                    // A linked song's chip leads with its own title — the tag
                    // alone ("V2") would not say which song it is.
                    Text(showsTitle ? entry.version.name : (entry.version.versionTag ?? entry.version.name))
                        .font(.caption.weight(.bold))
                        .lineLimit(1)
                    // The chip's own badge, as in VersionRowView, so the ⭐ version stands out.
                    if let b = entry.version.badge, let badge = Badge(rawValue: b) {
                        Text(badge.emoji)
                            .font(.caption2)
                            .accessibilityLabel(badge.label)
                    }
                }
                // Era name: the reason this picker reaches across eras at
                // all, so every chip says where its version lives.
                Text(entry.eraName)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                BadgeRowView(version: entry.version)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(minWidth: 96, alignment: .leading)
            .background(isSelected ? (accentColor ?? .lsAccent).opacity(0.22) : Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(isSelected ? (accentColor ?? .lsAccent) : .clear, lineWidth: 1.5)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .rowHoverHighlight()
    }

    // MARK: - Credits section

    @ViewBuilder
    private var creditsSection: some View {
        let credits: [(String, String)] = [
            ("feat.", active.version.featuring),
            ("prod.", active.version.producers),
            ("with", active.version.collaboration),
            ("ref.", active.version.refs),
            ("artist", active.version.creditedArtists),
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
        // Date cells are shown verbatim, digits or not: trackers write "Spring" or
        // "Late 2004 sessions", and hiding them loses information.
        let items: [(String, String)] = [
            ("Version", active.version.versionTag),
            ("Duration", active.version.trackLength),
            ("File Date", active.version.fileDate),
            ("Leak Date", active.version.leakDate),
            ("Preview Date", active.version.previewDate),
            ("Type", active.version.type),
            ("Recording", active.version.dateOfRecording),
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

    /// Favourite the whole song when one's known, else just this version —
    /// same branch the sticky bottom bar and the overflow menu both need.
    private func toggleFavourite() {
        if let song = active.song, let slug = payload.artistSlug {
            favourites.toggle(
                song: song,
                artistSlug: slug,
                artistName: payload.artistName,
                sourceUrl: nil,
                eraName: active.eraName,
                eraArt: active.eraArt
            )
        } else {
            let slug = payload.artistSlug ?? payload.artistName.slugified
            favourites.toggleFromVersion(
                version: active.version,
                artistSlug: slug,
                artistName: payload.artistName,
                sourceUrl: nil,
                eraName: active.eraName,
                eraArt: active.eraArt
            )
        }
    }
}
