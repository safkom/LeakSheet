import SwiftUI

/// Everything about one era: its description, dates, quality mix, the tracker's own
/// counts, timeline, credits and sections, with era-wide playback.
/// Sheet on iOS, inspector tab (`embedded`) on the Mac.
struct EraInfoSheet: View {
    @State private var eraName: String
    let embedded: Bool

    init(eraName: String, embedded: Bool = false) {
        _eraName = State(initialValue: eraName)
        self.embedded = embedded
    }

    @Environment(ArtistViewModel.self) private var vm
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme
    @State private var accentColor: Color?
    /// The credit page the embedded form presents, since it has no stack to push onto.
    @State private var creditSheet: CreditRef?

    private var era: Era? { vm.artist.eras.first { $0.name == eraName } }

    var body: some View {
        if embedded {
            content.sheet(item: $creditSheet) { CreditPageSheet(ref: $0) }
        } else {
            NavigationStack {
                content
                    .navigationTitle("Era")
                    #if os(iOS)
                    .toolbarTitleDisplayMode(.inline)
                    #endif
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Done") { dismiss() }
                        }
                    }
                    .navigationDestination(for: CreditRef.self) { CreditPageView(ref: $0) }
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        }
    }

    @ViewBuilder
    private var content: some View {
        if let era {
            let insights = EraInsights.compute(era: era, artist: vm.artist)
            let listening = ListeningHistory.eraListening(era, entries: ListeningHistory.shared.entries(for: vm.artist.slug))
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        header(era, insights)
                        if let desc = era.description, !desc.isEmpty { descriptionCard(desc) }
                        InfoGrid(items: [
                            ("Leaked", insights.leakDates.map(rangeText)),
                            ("File Dates", insights.fileDates.map(rangeText)),
                            ("Tracker Total", era.stats?.statedTotal.flatMap { $0 > 0 ? "\($0)" : nil }),
                        ])
                        listeningCard(listening)
                        qualitySection(insights)
                        trackerCounts(era.stats)
                        if let events = era.timeline, !events.isEmpty {
                            CardSection(title: "Timeline") { EraTimelineList(events: events) }
                        }
                        creditSection("Producers", insights.topProducers, role: .producer)
                        creditSection("Featuring", insights.topFeatures, role: .feature)
                        sectionBars(insights.sections)
                        miscTiles(Self.typeCounts(insights.miscEntries))
                        neighbours(insights)
                    }
                    .padding(20)
                }
                playBar
            }
            .background(background)
            .id(eraName)
        } else {
            ContentUnavailableView("Era Not Found", systemImage: "questionmark.square.dashed")
        }
    }

    // MARK: - Sections

    private func header(_ era: Era, _ insights: EraInsights) -> some View {
        VStack(spacing: 10) {
            if let artUrl = era.artUrl, let url = APIClient.shared.imageProxyURL(for: artUrl, width: 640) {
                CachedImage(url: url, maxPixelSize: 640) { ArtworkPlaceholder(cornerRadius: 0).font(.largeTitle) }
                    .frame(width: 160, height: 160)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .shadow(color: (accentColor ?? .clear).opacity(0.4), radius: 20, y: 8)
                    .task(id: artUrl) {
                        accentColor = await EraColorExtractor.shared.extractColor(from: url, cacheKey: artUrl)
                    }
                    .accessibilityHidden(true)
            }
            Text(era.name)
                .font(.title2.weight(.bold))
                .multilineTextAlignment(.center)
                .foregroundStyle((accentColor ?? .white).ensureReadable(against: .lsBackground, in: colorScheme))
            if let alts = era.altNames, !alts.isEmpty {
                Text(alts.joined(separator: " · "))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .accessibilityLabel("Also known as \(alts.joined(separator: ", "))")
            }
            Text("\(insights.songCount.formatted()) songs · \(insights.versionCount.formatted()) tracks · \(insights.playableCount.formatted()) available")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private func descriptionCard(_ text: String) -> some View {
        Text(text)
            .font(.subheadline)
            .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.lsCard)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder
    private func listeningCard(_ listening: ListeningHistory.EraListening) -> some View {
        if listening.plays > 0, let last = listening.last, listening.versions > 0 {
            let fraction = Double(listening.heard) / Double(listening.versions)
            CardSection(title: "Your Listening") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Heard \(listening.heard) of \(listening.versions) tracks (\(Int((fraction * 100).rounded()))%)")
                        .font(.subheadline)
                    ProgressView(value: fraction)
                        .tint(Color.lsAccent)
                        .accessibilityHidden(true)
                    Text("Last played \(last.formatted(.relative(presentation: .named)))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
                .background(Color.lsCard)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .accessibilityElement(children: .combine)
            }
        }
    }

    @ViewBuilder
    private func qualitySection(_ insights: EraInsights) -> some View {
        if !insights.quality.isEmpty {
            CardSection(title: "Quality") {
                VStack(alignment: .leading, spacing: 8) {
                    QualityBar(segments: insights.quality.map { (value: $0.count, color: $0.variant.color) })
                        .frame(height: 8)
                    ForEach(insights.quality, id: \.variant) { tier in
                        countRow(Self.label(for: tier.variant), "\(tier.count)", dot: tier.variant.color)
                    }
                }
                .padding(12)
                .background(Color.lsCard)
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    /// The counts the tracker states in its era header, which can differ from what parsed.
    @ViewBuilder
    private func trackerCounts(_ stats: EraStats?) -> some View {
        let items: [StatGrid.Item] = stats.map { s in
            // Tinted like the availability pills on the rows, so the two read as one vocabulary.
            [StatGrid.Item(label: "OG Files", value: s.ogFiles ?? 0, tint: BadgeVariant.ogfile.color),
             StatGrid.Item(label: "Full", value: max(s.full ?? 0, s.totalFull ?? 0), tint: BadgeVariant.full.color),
             StatGrid.Item(label: "Tagged", value: s.tagged ?? 0, tint: BadgeVariant.tagged.color),
             StatGrid.Item(label: "Partial", value: s.partial ?? 0, tint: BadgeVariant.partial.color),
             StatGrid.Item(label: "Snippets", value: s.snippets ?? 0, tint: BadgeVariant.snippet.color),
             StatGrid.Item(label: "Stem Bounces", value: s.stemBounces ?? 0, tint: BadgeVariant.stem.color),
             StatGrid.Item(label: "Unavailable", value: s.unavailable ?? 0, tint: .secondary)]
            + (s.releaseTypes ?? [:]).sorted { $0.key < $1.key }.map { StatGrid.Item(label: $0.key.capitalized, value: $0.value) }
        }?.filter { $0.value > 0 } ?? []
        if !items.isEmpty {
            CardSection(title: "Tracker Counts") { StatGrid(items: items) }
        }
    }

    @ViewBuilder
    private func creditSection(_ title: String, _ counts: [EraInsights.Count], role: ArtistViewModel.CreditRole) -> some View {
        if !counts.isEmpty {
            CardSection(title: title) {
                FlowLayout(spacing: 6) {
                    ForEach(counts) { c in
                        CreditNameLink(
                            ref: CreditRef(key: CreditNames.key(c.label), role: role),
                            text: "\(c.label) · \(c.value)",
                            spokenLabel: "\(c.label), \(c.value) tracks",
                            pushes: !embedded,
                            onOpen: { creditSheet = $0 }
                        )
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func sectionBars(_ sections: [EraInsights.Count]) -> some View {
        if !sections.isEmpty {
            CardSection(title: "Sections") {
                BarList(rows: sections.map { .init(label: $0.label, value: $0.value, unit: $0.value == 1 ? "song" : "songs") })
            }
        }
    }

    @ViewBuilder
    private func miscTiles(_ counts: [(String, Int)]) -> some View {
        if !counts.isEmpty {
            CardSection(title: "Misc & Videos") {
                StatGrid(items: counts.map { StatGrid.Item(label: $0.0, value: $0.1) })
            }
        }
    }

    @ViewBuilder
    private func neighbours(_ insights: EraInsights) -> some View {
        if insights.previousEra != nil || insights.nextEra != nil {
            HStack {
                if let prev = insights.previousEra {
                    Button { eraName = prev } label: { Label(prev, systemImage: "chevron.left").lineLimit(1) }
                        .accessibilityLabel("Previous era, \(prev)")
                }
                Spacer(minLength: 12)
                if let next = insights.nextEra {
                    Button { eraName = next } label: {
                        Label(next, systemImage: "chevron.right").labelStyle(TrailingIconLabelStyle()).lineLimit(1)
                    }
                    .accessibilityLabel("Next era, \(next)")
                }
            }
            .font(.subheadline)
            .buttonStyle(.bordered)
        }
    }

    // MARK: - Chrome

    @ViewBuilder
    private var playBar: some View {
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

    private var background: some View {
        ZStack {
            Color.lsBackground
            if let accent = accentColor {
                LinearGradient(colors: [accent.opacity(0.15), .clear], startPoint: .top, endPoint: .center)
            }
        }
        .ignoresSafeArea()
    }

    // MARK: - Helpers

    private func countRow(_ label: String, _ value: String, dot: Color? = nil) -> some View {
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

    private func rangeText(_ range: EraInsights.DateRange) -> String {
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

/// Icon after the title, for a "Next ›" button.
private struct TrailingIconLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 4) {
            configuration.title
            configuration.icon
        }
    }
}
