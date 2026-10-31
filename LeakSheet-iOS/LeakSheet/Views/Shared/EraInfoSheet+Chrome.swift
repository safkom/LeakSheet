import SwiftUI

extension EraInfoSheet {
    // MARK: - Chrome

    @ViewBuilder
    var playBar: some View {
        if let filtered = vm.filteredEra(named: eraName), !filtered.streamableVersions.isEmpty {
            HStack(spacing: 12) {
                Button {
                    Haptics.light()
                    player.playEra(filtered, artistName: vm.artist.name, artistSlug: vm.artist.slug)
                    if !embedded { dismiss() }
                } label: {
                    Label("Play Era", systemImage: "play.fill")
                        .font(.headline)
                        .foregroundStyle(Color.preferredText(on: accentColor ?? .lsAccent, in: colorScheme))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(accentColor ?? Color.lsAccent)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                Button {
                    Haptics.light()
                    player.shuffleEra(filtered, artistName: vm.artist.name, artistSlug: vm.artist.slug)
                    if !embedded { dismiss() }
                } label: {
                    Image(systemName: "shuffle")
                        .font(.headline)
                        .frame(width: 52, height: 52)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Shuffle era")
                Button {
                    Haptics.light()
                    player.playEraRadio(filtered, artistName: vm.artist.name, artistSlug: vm.artist.slug)
                    if !embedded { dismiss() }
                } label: {
                    Image(systemName: "dot.radiowaves.left.and.right")
                        .font(.headline)
                        .frame(width: 52, height: 52)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Era radio")
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
    }

    var background: some View {
        ZStack {
            Color.lsBackground
            if let accent = accentColor {
                LinearGradient(colors: [accent.opacity(0.15), .clear], startPoint: .top, endPoint: .center)
            }
        }
        .ignoresSafeArea()
    }

    // MARK: - Helpers

    func countRow(_ label: String, _ value: String, dot: Color? = nil) -> some View {
        HStack(spacing: 8) {
            if let dot {
                Circle().fill(dot).frame(width: 8, height: 8).accessibilityHidden(true)
            }
            Text(label).font(.subheadline)
            Spacer(minLength: 8)
            Text(value).font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }

    /// Misc entries counted per type, largest first: an era can hold dozens of them.
    static func typeCounts(_ entries: [MiscEntry]) -> [(String, Int)] {
        var counts: [String: Int] = [:]
        for entry in entries {
            let type = entry.entryType ?? ""
            counts[type.isEmpty ? "Other" : type, default: 0] += 1
        }
        let sorted = counts.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }
        return sorted.map { ($0.key, $0.value) }
    }

    func rangeText(_ range: EraInsights.DateRange) -> String {
        range.first == range.last ? range.first : "\(range.first) – \(range.last)"
    }

    static func label(for variant: BadgeVariant) -> String {
        switch variant {
        case .lossless: "Lossless"
        case .og: "OG"
        case .cd: "CD Quality"
        case .hq: "High Quality"
        case .rec: "Recording"
        case .lq: "Low Quality"
        case .beatonly: "Beat Only"
        default: "Unknown"
        }
    }
}
