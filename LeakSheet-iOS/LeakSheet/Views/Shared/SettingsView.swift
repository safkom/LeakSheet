import SwiftUI

/// App settings — streaming quality mode and other preferences.
struct SettingsView: View {
    @AppStorage("leaksheet_streaming_mode") private var useOriginalQuality: Bool = false
    @Environment(\.dismiss) private var dismiss

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
