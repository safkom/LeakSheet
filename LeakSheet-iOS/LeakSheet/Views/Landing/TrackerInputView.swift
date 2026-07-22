import SwiftUI

/// URL input bar with paste button / parse button and cold-load progress.
struct TrackerInputView: View {
    @Binding var url: String
    var loading: Bool
    var loadPhase: APIClient.LoadPhase?
    var onSubmit: () async -> Void

    @FocusState private var focused: Bool
    @State private var selection: TextSelection?

    var body: some View {
        VStack(spacing: 6) {
            inputRow
            if loading, let loadPhase {
                progressRow(for: loadPhase)
                    .transition(.opacity)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .glassEffect(focused ? .regular.tint(.lsAccent) : .regular, in: .rect(cornerRadius: 12))
        .animation(.default, value: loading)
    }

    private var inputRow: some View {
        HStack(spacing: 8) {
            Image(systemName: "link")
                .foregroundStyle(.secondary)
                .font(.subheadline)

            TextField("Paste a tracker URL...", text: $url, selection: $selection)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .textContentType(.URL)
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
                        .frame(width: 44, height: 44)   // 44pt HIG hit target
                        .contentShape(Rectangle())
                }
                .disabled(loading)
                .accessibilityLabel("Clear URL")
            }

            if url.trimmingCharacters(in: .whitespaces).isEmpty {
                Button {
                    pasteFromClipboard()
                } label: {
                    Label("Paste", systemImage: "doc.on.clipboard")
                        .font(.subheadline)
                }
                .disabled(loading)
                .foregroundStyle(.secondary)
            } else {
                Button {
                    normalizeIfConcatenated()
                    Task { await onSubmit() }
                } label: {
                    if loading {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Text("Parse")
                            .font(.subheadline.weight(.semibold))
                    }
                }
                .disabled(loading || url.trimmingCharacters(in: .whitespaces).isEmpty)
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }
        }
    }

    /// One line of honest progress: fraction when the payload size is known,
    /// a byte counter otherwise, and a phase label either way.
    @ViewBuilder
    private func progressRow(for phase: APIClient.LoadPhase) -> some View {
        HStack(spacing: 8) {
            switch phase {
            case .connecting:
                ProgressView()
                    .controlSize(.mini)
                Text("Contacting server…")
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

    private func pasteFromClipboard() {
        if let text = UIPasteboard.general.string {
            url = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }

    /// Backstop against a concatenated result reaching submit — e.g.
    /// "https://a.com/xhttps://b.com/y" from a partial retype before
    /// select-all-on-focus existed. Keeps only the last "http" occurrence,
    /// which is the URL the user most recently typed or pasted.
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
