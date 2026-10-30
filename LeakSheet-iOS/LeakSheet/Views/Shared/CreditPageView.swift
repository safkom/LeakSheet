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
                .init(label: "Available", value: profile.playableCount, tint: BadgeVariant.full.color),
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

    private func bestCard(_ c: CreditProfile.Credited, _ profile: CreditProfile) -> some View {
        let badge = c.version.badge.flatMap(Badge.init(rawValue:))
        return VStack(alignment: .leading, spacing: 6) {
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

    // MARK: - Rows and chrome

    /// Title, tag and badge on one line over the quality pills, with the play control
    /// centred beside both: the era list's nested version row assumes a song header above it.
    private func trackRow(_ c: CreditProfile.Credited, _ profile: CreditProfile) -> some View {
        let isCurrent = player.isNowPlaying(c.version, inEra: c.eraName)
        let heard = ListeningHistory.shared.isHeard(c.version, artistSlug: vm.artist.slug, eraName: c.eraName)
        let detail = [c.version.trackLength, c.version.leakDate]
            .compactMap { $0?.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && $0 != "?:??" }
            .joined(separator: " · ")
        return HStack(spacing: 10) {
            SongPlayControl(
                isCurrent: isCurrent, isLoading: player.loading, isPlaying: player.isPlaying,
                canStream: c.version.isStreamable, title: c.version.name, link: c.version.streamableLink,
                play: { play(c.version, in: profile.streamable) }
            )
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(c.song.baseName)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(isCurrent ? Color.lsAccent : .primary)
                        .lineLimit(1)
                    if heard {
                        HeardDot()
                    }
                    if let tag = c.version.versionTag {
                        Text(tag)
                            .font(.caption.weight(.bold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    if let badge = c.version.badge.flatMap(Badge.init(rawValue:)) {
                        Text(badge.emoji).font(.caption)
                    }
                }
                BadgeRowView(version: c.version, trailing: detail.isEmpty ? nil : detail)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            ThreeDotMenu(
                version: c.version, song: c.song,
                artistName: vm.artist.name, artistSlug: vm.artist.slug, sourceUrl: vm.artist.sourceUrl,
                eraName: c.eraName, eraArt: c.eraArt,
                onPlay: { play($0, in: profile.streamable) }, onShowDescription: { description = $0 }
            )
        }
        .padding(.vertical, 8)
        .contentShape(Rectangle())
        .onTapGesture { description = payload(c) }
        .accessibilityElement(children: .combine)
        .accessibilityValue(heard ? "played" : "")
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Shows details")
    }

    private func payload(_ c: CreditProfile.Credited) -> DescriptionSheet.Payload {
        DescriptionSheet.Payload(
            song: c.song, version: c.version, artistName: vm.artist.name, artistSlug: vm.artist.slug,
            eraName: c.eraName, eraArt: c.eraArt
        )
    }

    static func count(_ n: Int, _ noun: String) -> String {
        "\(n.formatted()) \(n == 1 ? noun : noun + "s")"
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
                Button {
                    Haptics.light()
                    player.playCreditRadio(list, artistName: vm.artist.name, artistSlug: vm.artist.slug)
                } label: {
                    Image(systemName: "dot.radiowaves.left.and.right")
                        .font(.headline)
                        .frame(width: 52, height: 52)
                        .background(Color.lsCard)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Radio")
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
