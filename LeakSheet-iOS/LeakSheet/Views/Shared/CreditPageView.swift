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
        Text(text)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
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

    @Environment(ArtistViewModel.self) private var vm
    @Environment(PlayerViewModel.self) private var player
    @Environment(\.colorScheme) private var colorScheme

    @State private var role: ArtistViewModel.CreditRole
    @State private var profile: CreditProfile?
    /// Set after the first compute, so a name with no page shows a message, not a spinner.
    @State private var resolved = false
    @State private var description: DescriptionSheet.Payload?

    init(ref: CreditRef) {
        self.ref = ref
        _role = State(initialValue: ref.role)
    }

    var body: some View {
        Group {
            if let profile {
                VStack(spacing: 0) {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 18) {
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
        return VStack(spacing: 6) {
            Text(profile.name)
                .font(.title2.weight(.bold))
                .multilineTextAlignment(.center)
            Text(profile.role == .producer ? "Producer" : "Featured")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text("\(profile.songCount.formatted()) songs · \(profile.versionCount.formatted()) tracks · \(profile.playableCount.formatted()) available")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            Text("Active: \(active)")
                .font(.caption)
                .foregroundStyle(.secondary)
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

    @ViewBuilder
    private func bestOfSection(_ profile: CreditProfile) -> some View {
        if !profile.bestOf.isEmpty {
            CardSection(title: "Best Of") {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(profile.bestOf) { c in versionRow(c, profile) }
                }
            }
        }
    }

    @ViewBuilder
    private func erasSection(_ profile: CreditProfile) -> some View {
        if !profile.topEras.isEmpty {
            countCard("Most Active Eras") {
                ForEach(profile.topEras) { c in countRow(c.label, "\(c.value) tracks") }
            }
        }
    }

    @ViewBuilder
    private func qualitySection(_ profile: CreditProfile) -> some View {
        if !profile.quality.isEmpty {
            countCard("Quality") {
                QualityBar(segments: profile.quality.map { (value: $0.count, color: $0.variant.color) })
                    .frame(height: 8)
                ForEach(Array(profile.quality.enumerated()), id: \.offset) { _, tier in
                    countRow(EraInfoSheet.label(for: tier.variant), "\(tier.count)", dot: tier.variant.color)
                }
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
        CardSection(title: "All Songs") {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(Array(profile.eras.enumerated()), id: \.offset) { _, era in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(era.eraName)
                            .font(.subheadline.weight(.semibold))
                            .padding(.leading, 4)
                        ForEach(era.versions) { c in versionRow(c, profile) }
                    }
                }
            }
        }
    }

    // MARK: - Rows and chrome

    private func versionRow(_ c: CreditProfile.Credited, _ profile: CreditProfile) -> some View {
        VersionRowView(
            version: c.version, song: c.song,
            artistName: vm.artist.name, artistSlug: vm.artist.slug, sourceUrl: vm.artist.sourceUrl,
            eraName: c.eraName, eraArt: c.eraArt,
            onPlay: { play($0, in: profile.streamable) },
            onShowDescription: { description = $0 }
        )
    }

    private func countCard<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        CardSection(title: title) {
            VStack(spacing: 6) { content() }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.lsCard)
                .clipShape(RoundedRectangle(cornerRadius: 10))
        }
    }

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

    @ViewBuilder
    private func playBar(_ profile: CreditProfile) -> some View {
        let list = profile.streamable
        if !list.isEmpty {
            HStack(spacing: 12) {
                Button {
                    Haptics.light()
                    player.playInList(items(list), startAt: 0)
                } label: {
                    Label("Play All", systemImage: "play.fill")
                        .font(.headline)
                        .foregroundStyle(Color.preferredText(on: .lsAccent, in: colorScheme))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(Color.lsAccent)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                Button {
                    Haptics.light()
                    player.playInList(items(list.shuffled()), startAt: 0)
                } label: {
                    Image(systemName: "shuffle")
                        .font(.headline)
                        .frame(width: 52, height: 52)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Shuffle all tracks")
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
    }

    // MARK: - Playback

    private func items(_ list: [CreditProfile.Credited]) -> [PlaybackListItem] {
        list.map {
            PlaybackListItem(
                version: $0.version, artistName: vm.artist.name, eraName: $0.eraName,
                artUrl: $0.eraArt ?? "", artistSlug: vm.artist.slug
            )
        }
    }

    /// Starts the streamable list at the tapped version, so auto-advance continues down it.
    private func play(_ version: SongVersion, in list: [CreditProfile.Credited]) {
        guard let idx = list.firstIndex(where: { $0.version == version }) else { return }
        Haptics.light()
        player.playInList(items(list), startAt: idx)
    }
}

/// Hosts a credit page in its own stack with a Done button, for hosts without one.
struct CreditPageSheet: View {
    let ref: CreditRef
    @Environment(\.dismiss) private var dismiss

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
