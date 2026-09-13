import SwiftUI

/// App settings — streaming quality mode and other preferences.
struct SettingsView: View {
    @AppStorage("leaksheet_streaming_mode") private var useOriginalQuality: Bool = false
    @AppStorage(AudioEngine.autoplayNextKey) private var autoplayNext: Bool = true
    @AppStorage(APIClient.baseURLDefaultsKey) private var customServerURL: String = ""
    @AppStorage(AppAppearance.storageKey) private var appearance: AppAppearance = .platformDefault
    @Environment(\.dismiss) private var dismiss

    /// Set when hosted as a sidebar destination rather than presented as a
    /// sheet — the host supplies the navigation chrome, so skip the wrapping
    /// NavigationStack and the Done button.
    var embedded = false

    /// The presenter's colour scheme, which follows the device once the root
    /// drops its override. Needed because `.preferredColorScheme(nil)` on a
    /// sheet does not release an override the sheet already applied: choosing
    /// System left this sheet dark on a light phone until it was closed.
    var presenterScheme: ColorScheme? = nil

    @State private var cacheSizeBytes: Int64 = 0
    @State private var imageCacheBytes: Int64 = 0
    @State private var clearingCache = false
    @State private var confirmingClearCache = false

    /// Shown so a sideloaded build can be identified. Without it there was no
    /// way to say which version you were running.
    private var appVersion: String {
        let info = Bundle.main.infoDictionary
        let short = info?["CFBundleShortVersionString"] as? String ?? "—"
        let build = info?["CFBundleVersion"] as? String ?? "—"
        return "\(short) (\(build))"
    }

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
                // The app root applies the appearance to the window, and sheets
                // opened afterwards inherit it — but this sheet is already on
                // screen when the choice changes here, and a presented sheet is
                // its own presentation. Without this it stayed in the old
                // appearance until closed.
                .preferredColorScheme(appearance.colorScheme ?? presenterScheme)
        }
    }

    private var settingsList: some View {
            List {
                SwiftUI.Section {
                    Picker("Appearance", selection: $appearance) {
                        ForEach(AppAppearance.allCases) { option in
                            Text(option.label).tag(option)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                } header: {
                    Text("Appearance")
                }

                SwiftUI.Section {
                    // The stock inline picker: a checkmark row per option, with
                    // selection announced by VoiceOver for free. This used to be
                    // a hand-rolled pair of buttons drawing checkmark/circle
                    // glyphs and adding .isSelected traits by hand.
                    Picker("Playback Quality", selection: $useOriginalQuality) {
                        qualityLabel(
                            title: "Streaming",
                            subtitle: "Uses provider's streaming API — can use compression on some formats"
                        )
                        .tag(false)
                        qualityLabel(
                            title: "Original",
                            subtitle: "Uses the provider's original file - may use more data for Lossless files"
                        )
                        .tag(true)
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()
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
                    HStack {
                        Text("Cached images")
                            .font(.subheadline)
                        Spacer()
                        Text(imageCacheBytes.formatted(.byteCount(style: .file)))
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    Button(role: .destructive) {
                        confirmingClearCache = true
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
                    .confirmationDialog(
                        "Clear cached trackers and images?",
                        isPresented: $confirmingClearCache,
                        titleVisibility: .visible
                    ) {
                        Button("Clear Cache", role: .destructive, action: clearCache)
                    } message: {
                        Text("Frees \((cacheSizeBytes + imageCacheBytes).formatted(.byteCount(style: .file))). Trackers re-download the next time you open them.")
                    }
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
                        Text("Leave empty to use the default server. For a local backend, enter its full address — for example http://192.168.1.20:8000.")
                    }
                }

                SwiftUI.Section {
                    HStack {
                        Text("Version")
                            .font(.subheadline)
                        Spacer()
                        Text(appVersion)
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("About")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.lsBackground)
            .navigationTitle("Settings")
            #if os(iOS)
            .toolbarTitleDisplayMode(.inline)
            #endif
            .task {
                cacheSizeBytes = await CacheService.shared.cacheSizeBytes()
                imageCacheBytes = await ImageCache.shared.diskUsageBytes()
            }
            .toolbar {
                if !embedded {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
            }
    }

    private func qualityLabel(title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.subheadline.weight(.medium))
            Text(subtitle)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func clearCache() {
        clearingCache = true
        Task {
            await CacheService.shared.clearCache()
            await ImageCache.shared.clearAll()
            cacheSizeBytes = await CacheService.shared.cacheSizeBytes()
            imageCacheBytes = await ImageCache.shared.diskUsageBytes()
            clearingCache = false
        }
    }
}
