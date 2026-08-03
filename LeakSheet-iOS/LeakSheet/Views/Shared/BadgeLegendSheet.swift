import SwiftUI

/// A glossary of the quality / availability / badge vocabulary a tracker uses.
/// The terms ("Stem Bounce", "OG File", …) are opaque to newcomers — this
/// makes the color-coded pills legible without prior knowledge.
struct BadgeLegendSheet: View {
    @Environment(\.dismiss) private var dismiss

    private struct Term: Identifiable {
        let name: String
        let detail: String
        var id: String { name }
    }

    // Colors resolve through the same matchers the rows use, so the legend
    // always matches what's shown on a song.
    private static let quality: [Term] = [
        .init(name: "Lossless", detail: "Uncompressed studio quality (FLAC/WAV)."),
        .init(name: "CD Quality", detail: "Lossy but high-fidelity, ~320 kbps."),
        .init(name: "High Quality", detail: "Good lossy quality."),
        .init(name: "Recording", detail: "Captured from a playback, not a source file."),
        .init(name: "Low Quality", detail: "Compressed or degraded audio."),
        .init(name: "Not Available", detail: "No file is circulating."),
    ]

    private static let availability: [Term] = [
        .init(name: "OG File", detail: "The original leaked file, untouched."),
        .init(name: "Full", detail: "The complete track is out."),
        .init(name: "Tagged", detail: "Full, but watermarked with producer/DJ tags."),
        .init(name: "Partial", detail: "Only part of the track circulates."),
        .init(name: "Snippet", detail: "A short clip only."),
        .init(name: "Stem Bounce", detail: "Rendered from the individual track stems."),
        .init(name: "Beat Only", detail: "Instrumental / beat, no vocals."),
        .init(name: "Confirmed", detail: "Known to exist, but not circulating."),
        .init(name: "Rumored", detail: "Reported to exist — unverified."),
        .init(name: "Conflicting Sources", detail: "Sources disagree on the details."),
        .init(name: "Unavailable", detail: "Not obtainable."),
    ]

    private struct BadgeTerm: Identifiable {
        let badge: Badge
        let name: String
        let detail: String
        var id: String { badge.rawValue }
    }

    private static let badges: [BadgeTerm] = [
        .init(badge: .best, name: Badge.best.label, detail: "A standout track."),
        .init(badge: .special, name: Badge.special.label, detail: "Notable or highlighted."),
        .init(badge: .grail, name: Badge.grail.label, detail: "A highly sought-after holy grail."),
        .init(badge: .wanted, name: Badge.wanted.label, detail: "Actively wanted by the community."),
        .init(badge: .worst, name: Badge.worst.label, detail: "Widely disliked."),
        .init(badge: .ai, name: Badge.ai.label, detail: "AI-generated — not an authentic leak."),
    ]

    var body: some View {
        NavigationStack {
            List {
                SwiftUI.Section("Quality") {
                    ForEach(Self.quality) { swatchRow($0.name, $0.detail, color: qualityVariant($0.name).color) }
                }
                SwiftUI.Section("Availability") {
                    ForEach(Self.availability) { swatchRow($0.name, $0.detail, color: availabilityVariant($0.name).color) }
                }
                SwiftUI.Section("Badges") {
                    ForEach(Self.badges) { term in
                        badgeRow(term.badge.emoji, term.name, term.detail)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.lsBackground)
            .navigationTitle("Legend")
            .toolbarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func swatchRow(_ name: String, _ detail: String, color: Color) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Circle()
                .fill(color)
                .frame(width: 14, height: 14)
                .frame(width: 24, alignment: .center)
            textPair(name, detail)
        }
        .padding(.vertical, 2)
        .listRowBackground(Color.lsCard)
    }

    private func badgeRow(_ emoji: String, _ name: String, _ detail: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(emoji)
                .font(.title3)
                .frame(width: 24, alignment: .center)
            textPair(name, detail)
        }
        .padding(.vertical, 2)
        .listRowBackground(Color.lsCard)
    }

    private func textPair(_ name: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(name)
                .font(.subheadline.weight(.medium))
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
