import SwiftUI

extension SongDescriptionSheet {
    // MARK: - Version picker

    /// Horizontal chip row of every version of this song, including other eras' (see
    /// `pickerVersions`, read exactly once here: it is a cross-era lookup). A chip
    /// re-points the whole sheet via `active`.
    @ViewBuilder
    var versionPicker: some View {
        let versions = pickerVersions
        let linked = linkedVersions
        if versions.count > 1 || !linked.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                if versions.count > 1 {
                    chipRow(title: "Versions", entries: versions, showsTitle: false)
                }
                if !linked.isEmpty {
                    chipRow(title: "Also Known As", entries: linked, showsTitle: true)
                }
            }
        }
    }

    /// Opens scrolled to the version the sheet was opened for, so a deep version's
    /// chip isn't off-screen.
    private func chipRow(
        title: String, entries: [ArtistViewModel.CrossEraVersion], showsTitle: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(entries) { entry in
                            versionChip(entry, showsTitle: showsTitle)
                                .id(entry.id)
                        }
                    }
                    .padding(.vertical, 2)
                }
                .onAppear {
                    guard let selected = entries.first(where: isActive) else { return }
                    proxy.scrollTo(selected.id, anchor: .center)
                }
            }
        }
    }

    private func isActive(_ entry: ArtistViewModel.CrossEraVersion) -> Bool {
        entry.version.id == activeBaseID && entry.eraName == active.eraName
    }

    private func versionChip(_ entry: ArtistViewModel.CrossEraVersion, showsTitle: Bool) -> some View {
        let isSelected = isActive(entry)
        return Button {
            Haptics.light()
            active = ActiveVersion(
                version: entry.version, song: entry.song,
                eraName: entry.eraName, eraArt: entry.eraArt
            )
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 4) {
                    // A linked song's chip leads with its own title — the tag
                    // alone ("V2") would not say which song it is.
                    Text(showsTitle ? entry.version.name : (entry.version.versionTag ?? entry.version.name))
                        .font(.caption.weight(.bold))
                        .lineLimit(1)
                    // The chip's own badge, as in VersionRowView, so the ⭐ version stands out.
                    if let rawBadge = entry.version.badge, let badge = Badge(rawValue: rawBadge) {
                        Text(badge.emoji)
                            .font(.caption2)
                            .accessibilityLabel(badge.label)
                    }
                }
                // Era name: the reason this picker reaches across eras at
                // all, so every chip says where its version lives.
                Text(entry.eraName)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                BadgeRowView(version: entry.version)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(minWidth: 96, alignment: .leading)
            .background(isSelected ? (accentColor ?? .lsAccent).opacity(0.22) : Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(isSelected ? (accentColor ?? .lsAccent) : .clear, lineWidth: 1.5)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .rowHoverHighlight()
    }

    // MARK: - Credits section

    @ViewBuilder
    var creditsSection: some View {
        let credits: [(String, String)] = [
            ("feat.", active.version.featuring),
            ("prod.", active.version.producers),
            ("with", active.version.collaboration),
            ("ref.", active.version.refs),
            ("eng.", active.version.engineer),
            ("artist", active.version.creditedArtists)
        ].compactMap { label, val in
            guard let value = val, !value.isEmpty else { return nil }
            return (label, value)
        }

        if !credits.isEmpty {
            // One row per role, the label in a fixed column beside its names so it lines up
            // with the first pill instead of floating among them.
            VStack(alignment: .leading, spacing: 6) {
                ForEach(credits, id: \.0) { label, value in
                    HStack(alignment: .top, spacing: 8) {
                        Text(label)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.tertiary)
                            .frame(width: 44, alignment: .leading)
                            .padding(.vertical, 4)
                        FlowLayout(spacing: 6) {
                            if let role = Self.creditRole(label) {
                                ForEach(Array(CreditNames.split(value).enumerated()), id: \.offset) { _, name in
                                    creditName(name, role: role)
                                }
                            } else {
                                plainCredit(value)
                            }
                        }
                    }
                    .accessibilityElement(children: .contain)
                }
            }
        }
    }

    private func plainCredit(_ text: String) -> some View {
        Text(text)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Color.lsCard)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    /// The page role a credit label names, or nil for labels that stay plain text.
    private static func creditRole(_ label: String) -> ArtistViewModel.CreditRole? {
        switch label {
        // "with" is a collaboration; the credit index files it with features.
        case "feat.", "with": return .feature
        case "prod.": return .producer
        default: return nil
        }
    }

    /// One credited name: a link to its page when it has one, plain text otherwise.
    @ViewBuilder
    private func creditName(_ name: String, role: ArtistViewModel.CreditRole) -> some View {
        let key = CreditNames.key(name)
        if let viewModel = artistVM, CreditProfile.hasPage(
            key: key,
            role: role,
            artist: viewModel.artist,
            index: viewModel.creditIndex
        ) {
            CreditNameLink(
                ref: CreditRef(key: key, role: role), text: name,
                spokenLabel: "\(name), open page", pushes: !embedded,
                onOpen: { creditSheet = $0 }
            )
        } else {
            plainCredit(name)
        }
    }

    // MARK: - Detail grid

    var detailGrid: some View {
        // Date cells are shown verbatim, digits or not: trackers write "Spring" or
        // "Late 2004 sessions", and hiding them loses information.
        InfoGrid(items: [
            ("Version", active.version.versionTag),
            ("Duration", active.version.trackLength),
            ("File Date", active.version.fileDate),
            ("Leak Date", active.version.leakDate),
            ("Preview Date", active.version.previewDate),
            ("Type", active.version.type),
            ("Recording", active.version.dateOfRecording),
            ("Recorded At", active.version.recordingLocation)
        ])
    }

    // MARK: - Helpers

    /// Fan star rating (1-5) from the tracker's availability cell.
    func ratingPill(_ rating: Int) -> some View {
        HStack(spacing: 2) {
            ForEach(1...5, id: \.self) { star in
                Image(systemName: star <= rating ? "star.fill" : "star")
                    .font(.caption2)
                    .foregroundStyle(star <= rating ? Color.lsStar : Color.secondary)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Color.lsCard)
        .clipShape(Capsule())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Fan rating \(rating) of 5 stars")
    }

    /// Favourite the whole song when one's known, else just this version —
    /// same branch the sticky bottom bar and the overflow menu both need.
    func toggleFavourite() {
        if let song = active.song, let slug = payload.artistSlug {
            favourites.toggle(
                song: song,
                artistSlug: slug,
                artistName: payload.artistName,
                sourceUrl: nil,
                eraName: active.eraName,
                eraArt: active.eraArt
            )
        } else {
            let slug = payload.artistSlug ?? payload.artistName.slugified
            favourites.toggleFromVersion(
                version: active.version,
                artistSlug: slug,
                artistName: payload.artistName,
                sourceUrl: nil,
                eraName: active.eraName,
                eraArt: active.eraArt
            )
        }
    }
}
