import SwiftUI

/// App settings — streaming quality mode and other preferences.
struct SettingsView: View {
    @AppStorage("leaksheet_streaming_mode") private var useOriginalQuality: Bool = false
    @AppStorage(APIClient.baseURLDefaultsKey) private var customServerURL: String = ""
    @Environment(\.dismiss) private var dismiss

    private var customURLInvalid: Bool {
        let trimmed = customServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty
            && (!trimmed.lowercased().hasPrefix("http") || URL(string: trimmed) == nil)
    }

    var body: some View {
        NavigationStack {
            List {
                SwiftUI.Section {
                    VStack(alignment: .leading, spacing: 12) {
                        qualityOption(
                            title: "Streaming",
                            subtitle: "Uses provider's streaming API — can use compression on some formats",
                            isSelected: !useOriginalQuality
                        ) {
                            useOriginalQuality = false
                        }

                        Divider()
                            .background(Color.lsBorder)

                        qualityOption(
                            title: "Original",
                            subtitle: "Uses the provider's original file - may use more data for Lossless files",
                            isSelected: useOriginalQuality
                        ) {
                            useOriginalQuality = true
                        }
                    }
                    .padding(.vertical, 4)
                } header: {
                    Text("Playback Quality")
                }

                SwiftUI.Section {
                    TextField(APIClient.defaultBaseURL, text: $customServerURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.subheadline.monospaced())
                } header: {
                    Text("Backend Server")
                } footer: {
                    if customURLInvalid {
                        Text("Invalid URL — the default server will be used.")
                            .foregroundStyle(.orange)
                    } else {
                        Text("Leave empty to use the default server.")
                    }
                }
            }
            .listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .background(Color.lsBackground)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationBackground(.ultraThinMaterial)
    }

    private func qualityOption(title: String, subtitle: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.primary)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(Color.lsAccent)
                        .font(.body)
                } else {
                    Image(systemName: "circle")
                        .foregroundStyle(.tertiary)
                        .font(.body)
                }
            }
        }
        .buttonStyle(.plain)
    }
}
