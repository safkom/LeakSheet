import SwiftUI

/// A credited name as a pill that opens its page. Pushed when the host has a
/// NavigationStack; the Mac inspector has none, so it hands the ref to `onOpen`.
struct CreditNameLink: View {
    let ref: CreditRef
    let text: String
    let spokenLabel: String
    let pushes: Bool
    var onOpen: (CreditRef) -> Void = { _ in }

    var body: some View {
        if pushes {
            NavigationLink(value: ref) { pill }
                .buttonStyle(.plain)
        } else {
            Button { onOpen(ref) } label: { pill }
                .buttonStyle(.plain)
        }
    }

    private var pill: some View {
        HStack(spacing: 3) {
            Text(text)
            Image(systemName: "chevron.right")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
                .accessibilityHidden(true)
        }
            .font(.caption.weight(.medium))
            .foregroundStyle(.primary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .accessibilityLabel(spokenLabel)
    }
}

/// A producer's or featured artist's page: what they worked on, drawn from the loaded tracker.
/// Pushed onto a NavigationStack, so it declares none of its own.
struct CreditPageView: View {
    let ref: CreditRef

    @Environment(ArtistViewModel.self) var vm
    @Environment(PlayerViewModel.self) var player
    @Environment(\.colorScheme) var colorScheme

    @State var role: ArtistViewModel.CreditRole
    @State var profile: CreditProfile?
    /// Set after the first compute, so a name with no page shows a message, not a spinner.
    @State var resolved = false
    @State var description: DescriptionSheet.Payload?

    init(ref: CreditRef) {
        self.ref = ref
        _role = State(initialValue: ref.role)
    }

    var body: some View {
        Group {
            if let profile {
                VStack(spacing: 0) {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 24) {
                            header(profile)
                            if profile.otherRoleCount > 0 { rolePicker }
                            bestOfSection(profile)
                            erasSection(profile)
                            qualitySection(profile)
                            collaboratorSection(profile)
                            allSongsSection(profile)
                        }
                        .padding(20)
                    }
                    playBar(profile)
                }
            } else if resolved {
                ContentUnavailableView("No Credits", systemImage: "person.crop.circle.badge.questionmark")
            }
        }
        .background(Color.lsBackground.ignoresSafeArea())
        .navigationTitle(profile?.name ?? "Credits")
        #if os(iOS)
        .toolbarTitleDisplayMode(.inline)
        #endif
        .task(id: role) {
            profile = CreditProfile.compute(
                key: ref.key, role: role, artist: vm.artist,
                index: vm.creditIndex, displayNames: vm.creditDisplayNames
            )
            resolved = true
        }
        .sheet(item: $description) { SongDescriptionSheet(payload: $0) }
    }

    // MARK: - Sections

    private func header(_ profile: CreditProfile) -> some View {
        let active = profile.firstEra == profile.lastEra
            ? profile.firstEra : "\(profile.firstEra) – \(profile.lastEra)"
        return VStack(spacing: 12) {
            VStack(spacing: 6) {
                Text(profile.name)
                    .font(.largeTitle.weight(.bold))
                    .multilineTextAlignment(.center)
                    .minimumScaleFactor(0.7)
                Text(profile.role == .producer ? "Producer" : "Featured Artist")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.lsAccent)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Color.lsAccent.opacity(0.15), in: Capsule())
                Text(active)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .accessibilityLabel("Active from \(profile.firstEra) to \(profile.lastEra)")
            }
            StatGrid(items: [
                .init(label: profile.songCount == 1 ? "Song" : "Songs", value: profile.songCount),
                .init(label: profile.versionCount == 1 ? "Track" : "Tracks", value: profile.versionCount),
                .init(label: "Available", value: profile.playableCount, tint: BadgeVariant.full.color)
            ], minWidth: 90)
        }
        .frame(maxWidth: .infinity)
    }

    private var rolePicker: some View {
        Picker("Role", selection: $role) {
            Text("Producer").tag(ArtistViewModel.CreditRole.producer)
            Text("Featured").tag(ArtistViewModel.CreditRole.feature)
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .accessibilityLabel("Credit role")
    }

    /// The sheet's own picks (grail, best, special) as artwork cards in a carousel.
    @ViewBuilder
    private func bestOfSection(_ profile: CreditProfile) -> some View {
        if !profile.bestOf.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Best Of")
                        .font(.title3.weight(.bold))
                    Text("\(profile.bestOf.count)")
                        .font(.subheadline.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(alignment: .top, spacing: 12) {
                        ForEach(profile.bestOf) { c in bestCard(c, profile) }
                    }
                    .padding(.horizontal, 20)
                }
                .padding(.horizontal, -20)
            }
        }
    }

    private func bestCardArt(_ c: CreditProfile.Credited, _ profile: CreditProfile, badge: Badge?) -> some View {
    ZStack {
        if let art = c.eraArt, let url = APIClient.shared.imageProxyURL(for: art, width: 320) {
            CachedImage(url: url, maxPixelSize: 320) { ArtworkPlaceholder(cornerRadius: 0) }
        } else {
            ArtworkPlaceholder(cornerRadius: 0)
        }
    }
    .frame(width: 140, height: 140)
    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    .overlay(alignment: .topLeading) {
        if let badge {
            Text(badge.emoji)
                .font(.title3)
                .padding(6)
                .background(.ultraThinMaterial, in: Circle())
                .padding(6)
                .accessibilityHidden(true)
        }
    }
    .overlay(alignment: .bottomTrailing) {
        if c.version.isStreamable {
            Button { play(c.version, in: profile.streamable) } label: {
                Image(systemName: "play.fill")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(.white)
                    .frame(width: 34, height: 34)
                    .background(Color.lsAccent, in: Circle())
                    .shadow(radius: 4, y: 2)
            }
            .buttonStyle(.plain)
            .padding(8)
            .accessibilityLabel("Play \(c.song.baseName)")
        }
    }
    }

    private func bestCard(_ c: CreditProfile.Credited, _ profile: CreditProfile) -> some View {
        let badge = c.version.badge.flatMap(Badge.init(rawValue:))
        return VStack(alignment: .leading, spacing: 6) {
            bestCardArt(c, profile, badge: badge)
            Text(c.song.baseName)
                .font(.subheadline.weight(.semibold))
                .lineLimit(2)
            Text([c.version.versionTag, c.eraName].compactMap { $0 }.joined(separator: " · "))
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .frame(width: 140, alignment: .leading)
        .contentShape(Rectangle())
        .onTapGesture { description = payload(c) }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(c.song.baseName), \(badge.map { "\($0.rawValue), " } ?? "")\(c.eraName)")
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Shows details")
    }

    @ViewBuilder
    private func erasSection(_ profile: CreditProfile) -> some View {
        if !profile.topEras.isEmpty {
            CardSection(title: "Most Active Eras") {
                BarList(rows: profile.topEras.map { .init(
                    label: $0.label,
                    value: $0.value,
                    unit: $0.value == 1 ? "track" : "tracks"
                ) })
            }
        }
    }

    @ViewBuilder
    private func qualitySection(_ profile: CreditProfile) -> some View {
        if !profile.quality.isEmpty {
            CardSection(title: "Quality") {
                VStack(spacing: 6) {
                    QualityBar(segments: profile.quality.map { (value: $0.count, color: $0.variant.color) })
                        .frame(height: 8)
                    ForEach(Array(profile.quality.enumerated()), id: \.offset) { _, tier in
                        countRow(EraInfoSheet.label(for: tier.variant), "\(tier.count)", dot: tier.variant.color)
                    }
                }
                .padding(12)
                .background(Color.lsCard)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
    }

    @ViewBuilder
    private func collaboratorSection(_ profile: CreditProfile) -> some View {
        if !profile.collaborators.isEmpty {
            CardSection(title: "Frequent Collaborators") {
                FlowLayout(spacing: 6) {
                    ForEach(profile.collaborators) { c in
                        CreditNameLink(
                            ref: c.ref, text: "\(c.name) · \(c.sharedVersions)",
                            spokenLabel: "\(c.name), \(c.sharedVersions) shared tracks", pushes: true
                        )
                    }
                }
            }
        }
    }

    private func allSongsSection(_ profile: CreditProfile) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("All Songs")
                .font(.title3.weight(.bold))
            ForEach(Array(profile.eras.enumerated()), id: \.offset) { _, era in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        if let art = era.versions.first?.eraArt, let url = APIClient.shared.imageProxyURL(
                            for: art,
                            width: 96
                        ) {
                            CachedImage(url: url, maxPixelSize: 96) { ArtworkPlaceholder(cornerRadius: 0) }
                                .frame(width: 28, height: 28)
                                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                                .accessibilityHidden(true)
                        }
                        Text(era.eraName)
                            .font(.headline)
                        Spacer()
                        Text(Self.count(era.versions.count, "track"))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityAddTraits(.isHeader)
                    VStack(spacing: 0) {
                        ForEach(era.versions) { c in
                            trackRow(c, profile)
                            if c.id != era.versions.last?.id { Divider().padding(.leading, 44) }
                        }
                    }
                    .padding(.horizontal, 10)
                    .background(Color.lsCard)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
        }
    }

}

/// Hosts a credit page in its own stack with a Done button, for hosts without one.
struct CreditPageSheet: View {
    let ref: CreditRef
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            CreditPageView(ref: ref)
                .navigationDestination(for: CreditRef.self) { CreditPageView(ref: $0) }
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
        }
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
    }
}
