import SwiftUI

/// App settings — streaming quality mode and other preferences.
struct SettingsView: View {
    /// UserDefaults key gating end-of-track auto-advance (default on).
    static let autoplayNextKey = "leaksheet_autoplay_next"

    @AppStorage("leaksheet_streaming_mode") private var useOriginalQuality: Bool = false
    @AppStorage(Self.autoplayNextKey) private var autoplayNext: Bool = true
    @AppStorage(APIClient.baseURLDefaultsKey) private var customServerURL: String = ""
    @Environment(\.dismiss) private var dismiss

    /// Set when hosted as a sidebar destination rather than presented as a
    /// sheet — the host supplies the navigation chrome, so skip the wrapping
    /// NavigationStack and the Done button.
    var embedded = false

    @State private var cacheSizeBytes: Int64 = 0
    @State private var clearingCache = false

    private var customURLInvalid: Bool {
        let trimmed = customServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty
            && (!trimmed.lowercased().hasPrefix("http") || URL(string: trimmed) == nil)
    }

    var body: some View {
        if embedded {
            settingsList
        } else {
            NavigationStack { settingsList }
                .presentationBackground(.ultraThinMaterial)
        }
    }

    private var settingsList: some View {
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
                            .overlay(Color.lsBorder)

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
                    Toggle(isOn: $autoplayNext) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Autoplay next")
                                .font(.subheadline.weight(.medium))
                            Text("Continue to the next track when one ends")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .tint(Color.lsAccent)
                } header: {
                    Text("Playback")
                }

                SwiftUI.Section {
                    HStack {
                        Text("Cached trackers")
                            .font(.subheadline)
                        Spacer()
                        Text(cacheSizeBytes.formatted(.byteCount(style: .file)))
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    Button(role: .destructive) {
                        clearingCache = true
                        Task {
                            await CacheService.shared.clearCache()
                            await ImageCache.shared.clearAll()
                            cacheSizeBytes = await CacheService.shared.cacheSizeBytes()
                            clearingCache = false
                        }
                    } label: {
                        if clearingCache {
                            ProgressView()
                                .frame(maxWidth: .infinity)
                        } else {
                            Text("Clear cache")
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .disabled(clearingCache)
                } header: {
                    Text("Storage")
                } footer: {
                    Text("Trackers re-download on next open; images re-fetch as they appear.")
                }

                SwiftUI.Section {
                    TextField(APIClient.defaultBaseURL, text: $customServerURL)
                        .autocorrectionDisabled()
                        .urlFieldTraits()
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
            .scrollContentBackground(.hidden)
            .background(Color.lsBackground)
            .navigationTitle("Settings")
            .toolbarTitleDisplayMode(.inline)
            .task {
                cacheSizeBytes = await CacheService.shared.cacheSizeBytes()
            }
            .toolbar {
                if !embedded {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
            }
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
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
