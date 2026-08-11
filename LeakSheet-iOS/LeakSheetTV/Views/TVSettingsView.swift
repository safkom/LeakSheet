import SwiftUI

/// Settings. Same `@AppStorage` keys the phone writes, so a device sharing an
/// iCloud-synced defaults store sees consistent behaviour.
struct TVSettingsView: View {
    @AppStorage("leaksheet_streaming_mode") private var useOriginalQuality = false
    @AppStorage(AudioEngine.autoplayNextKey) private var autoplayNext = true
    @AppStorage(APIClient.baseURLDefaultsKey) private var customServerURL = ""

    @State private var cacheSizeBytes: Int64 = 0
    @State private var clearingCache = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 40) {
                    section("Playback Quality") {
                        Picker("Quality", selection: $useOriginalQuality) {
                            Text("Streaming").tag(false)
                            Text("Original").tag(true)
                        }
                        .pickerStyle(.segmented)
                        .frame(maxWidth: 700)
                        Text(useOriginalQuality
                             ? "Uses the provider's original file — more data for lossless."
                             : "Uses the provider's streaming API — may be compressed.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    section("Playback") {
                        Toggle("Autoplay next", isOn: $autoplayNext)
                            .frame(maxWidth: 700)
                        Text("Continue to the next track when one ends.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    section("Storage") {
                        Text("Cached trackers: \(cacheSizeBytes.formatted(.byteCount(style: .file)))")
                        Button(role: .destructive) {
                            clearingCache = true
                            Task {
                                await CacheService.shared.clearCache()
                                await ImageCache.shared.clearAll()
                                cacheSizeBytes = await CacheService.shared.cacheSizeBytes()
                                clearingCache = false
                            }
                        } label: {
                            if clearingCache { ProgressView() } else { Text("Clear cache") }
                        }
                        .disabled(clearingCache)
                    }

                    section("Backend Server") {
                        TextField(APIClient.defaultBaseURL, text: $customServerURL)
                            .autocorrectionDisabled()
                            .urlFieldTraits()
                            .frame(maxWidth: 900)
                        Text("Leave empty to use the default server.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(60)
            }
            .background(Color.lsBackground)
            .navigationTitle("Settings")
            .task { cacheSizeBytes = await CacheService.shared.cacheSizeBytes() }
        }
    }

    @ViewBuilder
    private func section(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(title)
                .font(.title3.weight(.semibold))
                .foregroundStyle(.secondary)
            content()
        }
        .focusSection()
    }
}
