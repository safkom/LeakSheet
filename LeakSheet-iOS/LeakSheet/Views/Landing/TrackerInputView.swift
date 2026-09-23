import SwiftUI

/// URL input bar with paste button / parse button and cold-load progress.
struct TrackerInputView: View {
    @Binding var url: String
    var loading: Bool
    var loadPhase: APIClient.LoadPhase?
    var onSubmit: () async -> Void

    @FocusState private var focused: Bool
    @State private var selection: TextSelection?
    /// Seconds spent in the current phase: `.connecting` is one long server-side wait,
    /// so the label escalates rather than sitting on "Contacting server…".
    @State private var phaseElapsed: TimeInterval = 0

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        VStack(spacing: 8) {
            inputRow
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                // Tint via opacity, not by swapping the tint in and out — see
                // DECISIONS.md::ArtistRowViews.swift::glass-tint-opacity.
                .glassEffect(.regular.tint(.lsAccent.opacity(focused ? 0.28 : 0)), in: .rect(cornerRadius: 12))
            // Below the glass, not inside it: growing the glass shape while
            // this faded in drew the line clipped under the field's edge.
            if loading, let loadPhase {
                progressRow(for: loadPhase)
                    .padding(.horizontal, 14)
                    .transition(.opacity)
                    .task(id: loadPhase) {
                        phaseElapsed = 0
                        while !Task.isCancelled {
                            try? await Task.sleep(for: .milliseconds(500))
                            if Task.isCancelled { break }
                            phaseElapsed += 0.5
                        }
                    }
            }
        }
        .animation(.default, value: loading)
    }

    private var inputRow: some View {
        // At accessibility sizes the action button gets its own line, so the
        // field keeps usable width instead of ~30pt beside a pinned button.
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .trailing, spacing: 8))
            : AnyLayout(HStackLayout(spacing: 8))
        return layout {
            fieldRow
            actionButton
        }
    }

    private var fieldRow: some View {
        HStack(spacing: 8) {
            Image(systemName: "link")
                .foregroundStyle(.secondary)
                .font(.subheadline)

            TextField("Paste a tracker URL...", text: $url, selection: $selection)
                .autocorrectionDisabled()
                .urlFieldTraits()
                .submitLabel(.go)
                .focused($focused)
                .disabled(loading)
                .onSubmit {
                    normalizeIfConcatenated()
                    Task { await onSubmit() }
                }
                .onChange(of: focused) { _, isFocused in
                    // Select-all on focus: retyping into a filled field
                    // replaces the old URL instead of appending to it.
                    if isFocused, !url.isEmpty {
                        selection = TextSelection(range: url.startIndex..<url.endIndex)
                    }
                }

            if !url.isEmpty {
                Button {
                    url = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.subheadline)
                        .foregroundStyle(.tertiary)
                        .frame(width: Metrics.hitTarget, height: Metrics.hitTarget)
                        .contentShape(Rectangle())
                }
                .disabled(loading)
                .accessibilityLabel("Clear URL")
            }
        }
    }

    @ViewBuilder
    private var actionButton: some View {
            if url.trimmingCharacters(in: .whitespaces).isEmpty {
                // The system PasteButton, not a Button reading the pasteboard: it is explicit
                // consent, so it never raises the "Allow Paste?" prompt.
                PasteButton(payloadType: String.self) { strings in
                    if let text = strings.first {
                        url = text.trimmingCharacters(in: .whitespacesAndNewlines)
                    }
                }
                .buttonBorderShape(.capsule)
                .controlSize(.regular)
                .disabled(loading)
            } else {
                Button {
                    normalizeIfConcatenated()
                    Task { await onSubmit() }
                } label: {
                    if loading {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        // One line at any text size, or the field's greedy width squeezes it into a
                        // letter-per-line column at accessibility sizes.
                        Text("Parse")
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(1)
                            .fixedSize(horizontal: true, vertical: false)
                    }
                }
                .disabled(loading || url.trimmingCharacters(in: .whitespaces).isEmpty)
                .buttonStyle(.borderedProminent)
                .controlSize(.regular)
            }
    }

    /// One line of honest progress: fraction when the payload size is known,
    /// a byte counter otherwise, and a phase label either way.
    @ViewBuilder
    private func progressRow(for phase: APIClient.LoadPhase) -> some View {
        HStack(spacing: 8) {
            switch phase {
            case .readingCache:
                ProgressView()
                    .controlSize(.mini)
                Text("Checking local copy…")
            case .connecting:
                // Only until the server's first message — or for the whole
                // wait on a server that does not stream progress.
                ProgressView()
                    .controlSize(.mini)
                Text(Self.connectingLabel(elapsed: phaseElapsed))
            case .server(let message, let done, let total):
                if let total, total > 0 {
                    ProgressView(value: Double(done ?? 0), total: Double(total))
                        .frame(maxWidth: 120)
                } else {
                    ProgressView()
                        .controlSize(.mini)
                }
                Text(message)
                    .contentTransition(.opacity)
            case .downloading(let received, let expected):
                if let expected, expected > 0 {
                    ProgressView(value: Double(received), total: Double(expected))
                        .frame(maxWidth: 120)
                    Text("\(Self.formatBytes(received)) of \(Self.formatBytes(expected))")
                } else {
                    ProgressView()
                        .controlSize(.mini)
                    Text("Downloading… \(Self.formatBytes(received))")
                }
            case .preparing:
                ProgressView()
                    .controlSize(.mini)
                Text("Preparing tracker…")
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    static func formatBytes(_ bytes: Int64) -> String {
        bytes.formatted(.byteCount(style: .file))
    }

    /// What the server is actually doing while we wait for the first byte: on a
    /// cold parse, fetching the sheet from Google and parsing it.
    static func connectingLabel(elapsed: TimeInterval) -> String {
        switch elapsed {
        case ..<1.5: "Contacting server…"
        case ..<5: "Fetching tracker…"
        default: "Parsing a large tracker…"
        }
    }

    /// Backstop against a concatenated result reaching submit
    /// ("https://a.com/xhttps://b.com/y"): keeps only the last "http" occurrence.
    private func normalizeIfConcatenated() {
        var ranges: [Range<String.Index>] = []
        var searchStart = url.startIndex
        while let match = url.range(of: "http", range: searchStart..<url.endIndex) {
            ranges.append(match)
            searchStart = match.upperBound
        }
        guard ranges.count > 1, let last = ranges.last else { return }
        url = String(url[last.lowerBound...])
    }
}
