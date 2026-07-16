import SwiftUI

/// URL input bar with paste button / parse button.
struct TrackerInputView: View {
    @Binding var url: String
    var loading: Bool
    var onSubmit: () async -> Void

    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "link")
                .foregroundStyle(.secondary)
                .font(.subheadline)

            TextField("Paste a tracker URL...", text: $url)
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

            if !url.isEmpty {
                Button {
                    url = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.subheadline)
                        .foregroundStyle(.tertiary)
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
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .glassEffect(focused ? .regular.tint(.lsAccent) : .regular, in: .rect(cornerRadius: 12))
    }

    private func pasteFromClipboard() {
        if let text = UIPasteboard.general.string {
            url = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }

    /// SwiftUI's TextField has no public API to select-all on focus, so
    /// retyping into an already-filled field can append rather than replace
    /// (the clear button above is the primary fix for that). As a backstop
    /// against a concatenated result actually reaching submit — e.g.
    /// "https://a.com/xhttps://b.com/y" from a partial retype — keep only
    /// the last "http" occurrence, which is the URL the user most recently
    /// typed or pasted.
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
