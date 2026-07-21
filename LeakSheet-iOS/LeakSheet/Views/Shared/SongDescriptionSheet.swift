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
                                if let q = payload.version.quality, !q.isEmpty {
                                    let variant = qualityVariant(q)
                                    badgePill(text: q, variant: variant)
                                }
                                if let a = payload.version.availableLength, !a.isEmpty {
                                    let variant = availabilityVariant(a)
                                    badgePill(text: a, variant: variant)
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
                                            Text(linkDomain(link.raw))
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
            .navigationBarTitleDisplayMode(.inline)
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
        let items: [(String, String)] = [
            ("Version", payload.version.versionTag),
            ("Duration", payload.version.trackLength),
            ("File Date", payload.version.fileDate),
            ("Leak Date", payload.version.leakDate),
            ("Type", payload.version.type),
            ("Recording", payload.version.dateOfRecording),
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

    private func linkDomain(_ urlString: String) -> String {
        guard let url = URL(string: urlString), let host = url.host else { return urlString }
        return host.replacingOccurrences(of: "www.", with: "")
    }
}

// MARK: - File Info section

/// Stream file info (container, codec, bitrate, sample rate, …) for the
/// version's streamable link. Loads from the backend /metadata endpoint;
/// when the provider has no metadata API (krakenfiles), falls back to the
/// format info the player captured for the currently playing track.
/// Separate View type so its async load state invalidates only this section.
private struct FileInfoSection: View {
    let version: SongVersion

    @Environment(PlayerViewModel.self) private var player

    private enum LoadState: Equatable {
        case loading
        case loaded(rows: [FileInfoRows.Row], source: String)
        case unavailable
    }

    @State private var state: LoadState = .loading

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            switch state {
            case .loading:
                HStack(spacing: 8) {
                    Text("File Info")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    ProgressView()
                        .controlSize(.mini)
                }
            case .loaded(let rows, let source):
                Text("File Info")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 10) {
                    ForEach(rows) { row in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(row.label)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.tertiary)
                            Text(row.value)
                                .font(.subheadline)
                                .foregroundStyle(.primary)
                        }
                    }
                }
                .padding(12)
                .background(Color.lsCard)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                Text(source)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            case .unavailable:
                Text("File Info")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text("File info unavailable")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
        .task(id: version.id) { await load() }
        .onChange(of: player.streamFormat) { _, newFormat in
            // The user may start playing this version while the sheet is up —
            // upgrade an empty section with the freshly captured format.
            guard state == .unavailable || state == .loading,
                  let format = newFormat, format.trackKey == version.id else { return }
            let rows = FileInfoRows.rows(from: format)
            if !rows.isEmpty {
                state = .loaded(rows: rows, source: "from player")
            }
        }
    }

    private func load() async {
        guard let link = version.streamableLink else {
            state = .unavailable
            return
        }
        // try? on purpose: a metadata failure is never worth surfacing in the
        // sheet — we just fall through to the player.
        if let meta = try? await APIClient.shared.fetchMetadata(for: link) {
            let rows = FileInfoRows.rows(from: meta)
            if !rows.isEmpty {
                let provider = meta.provider.map { "via \(FileInfoRows.providerName($0))" } ?? "via provider"
                state = .loaded(rows: rows, source: provider)
                return
            }
        }
        if player.currentTrack?.id == version.id, let format = player.streamFormat {
            let rows = FileInfoRows.rows(from: format)
            if !rows.isEmpty {
                state = .loaded(rows: rows, source: "from player")
                return
            }
        }
        // The concurrent onChange(of: player.streamFormat) handler may have
        // already published a good result while this awaited fetchMetadata —
        // don't clobber it just because this path came up empty.
        if state == .loading {
            state = .unavailable
        }
    }
}

/// Row building for the File Info section — pure and unit-testable.
nonisolated enum FileInfoRows {
    struct Row: Equatable, Identifiable {
        let label: String
        let value: String
        var id: String { label }
    }

    static func rows(from meta: FileMetadata) -> [Row] {
        var rows: [Row] = []
        func add(_ label: String, _ value: String?) {
            if let value, !value.isEmpty { rows.append(Row(label: label, value: value)) }
        }
        add("Container", meta.container)
        if let codec = meta.codec {
            let profile = meta.codecProfile.map { " (\($0))" } ?? ""
            add("Codec", codec + profile)
        }
        add("Bitrate", meta.bitrate)
        add("Sample Rate", meta.sampleRate)
        add("Bit Depth", meta.bitsPerSample)
        add("Channels", meta.channels.map(String.init))
        add("Lossless", meta.lossless.map { $0 ? "Yes" : "No" })
        add("Duration", meta.duration.map(formatDuration))
        // froste analysis extras
        if meta.bitrate == nil {
            add("Est. Bitrate", meta.estimatedBitrate.map { "\($0) kbps" })
        }
        add("Freq. Cutoff", meta.frequencyCutoff.map { String(format: "%.1f kHz", $0) })
        add("Quality Check", meta.qualityMismatch.map { $0 ? "Mismatch" : "OK" })
        // imgur file facts
        add("File Size", meta.fileSize.map {
            ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file)
        })
        add("MIME Type", meta.mimeType)
        add("Filename", meta.filename)
        return rows
    }

    static func rows(from format: StreamFormatInfo) -> [Row] {
        var rows: [Row] = []
        if let codec = format.codec {
            rows.append(Row(label: "Codec", value: codec))
        }
        if let bps = format.indicatedBitrateBps {
            rows.append(Row(label: "Bitrate", value: "\(Int((bps / 1000).rounded())) kbps"))
        }
        if let rate = format.sampleRateHz {
            rows.append(Row(label: "Sample Rate", value: "\(Int(rate)) Hz"))
        }
        if let channels = format.channels {
            rows.append(Row(label: "Channels", value: String(channels)))
        }
        return rows
    }

    static func providerName(_ provider: String) -> String {
        switch provider {
        case "pillows": return "pillows.su"
        case "froste": return "froste.lol"
        case "imgur": return "imgur.gg"
        default: return provider
        }
    }

    /// "139.8073469387755s" → "2:19"; passthrough for anything unparseable.
    static func formatDuration(_ raw: String) -> String {
        let trimmed = raw.hasSuffix("s") ? String(raw.dropLast()) : raw
        guard let seconds = Double(trimmed), seconds.isFinite, seconds >= 0 else { return raw }
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return "\(mins):\(String(format: "%02d", secs))"
    }
}

// MARK: - Evidence section

/// Labeled provenance links from the tracker's Sources column. Separate View
/// type so the (potentially long) link list is its own invalidation boundary.
private struct EvidenceSection: View {
    let sources: [SourceRef]
    /// Parent owns the in-app Safari sheet.
    var onOpenLink: (URL) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Evidence")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            ForEach(sources, id: \.url) { source in
                if let url = URL(string: source.url) {
                    Button {
                        onOpenLink(url)
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "doc.text.magnifyingglass")
                                .font(.caption2)
                            Text(source.label.isEmpty ? shortHost(source.url) : source.label)
                                .font(.caption)
                                .multilineTextAlignment(.leading)
                            Spacer(minLength: 0)
                            Image(systemName: "arrow.up.right")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                        .foregroundStyle(Color.lsAccent)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func shortHost(_ urlString: String) -> String {
        URL(string: urlString)?.host?.replacingOccurrences(of: "www.", with: "") ?? urlString
    }
}

// MARK: - Flow Layout (wrapping HStack)

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
