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
                    Task { await onSubmit() }
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
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .glassEffect(focused ? .regular.tint(.lsAccent) : .regular, in: .rect(cornerRadius: 12))
    }

    private func pasteFromClipboard() {
        if let text = UIPasteboard.general.string {
            url = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }
}
