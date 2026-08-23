import SwiftUI

/// The two self-contained sections of the song description sheet, split
/// out of it (2026-07-25) so each stays its own readable unit — and its
/// own SwiftUI invalidation boundary, which is why they were separate
/// `View` types to begin with.

// MARK: - File Info section

/// Stream file info (container, codec, bitrate, sample rate, …) for the
/// version's streamable link. Loads from the backend /metadata endpoint;
/// when the provider has no metadata API (krakenfiles), falls back to the
/// format info the player captured for the currently playing track.
/// Separate View type so its async load state invalidates only this section.
struct FileInfoSection: View {
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
        .task(id: version.id) {
            // Reset first. `.task(id:)` restarts the task but the view keeps
            // its identity, so @State survived a version switch — V1's codec,
            // bitrate and sample rate stayed on screen labelled as V2's,
            // because the tail guard below only writes .unavailable when the
            // state is still .loading.
            state = .loading
            await load()
        }
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
        return Format.time(seconds)
    }
}

// MARK: - Evidence section

/// Labeled provenance links from the tracker's Sources column. Separate View
/// type so the (potentially long) link list is its own invalidation boundary.
struct EvidenceSection: View {
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
                                .accessibilityHidden(true)
                            Text(source.label.isEmpty ? Format.shortHost(source.url) : source.label)
                                .font(.caption)
                                .multilineTextAlignment(.leading)
                            Spacer(minLength: 0)
                            Image(systemName: "arrow.up.right")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                                .accessibilityHidden(true)
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

}

