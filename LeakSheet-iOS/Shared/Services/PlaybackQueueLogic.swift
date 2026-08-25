import Foundation

/// Pure decision logic for playback ordering: the user queue, an era context
/// with artist-level rollover, and ad-hoc ordered lists (recents, search
/// results, a song's versions). Value type with no AVPlayer and no side
/// effects, so the ordering rules are unit-testable.
///
/// Positions are tracked with cursors rather than identity searches:
/// duplicate (name, versionTag) pairs — e.g. two distinct '???' mystery
/// tracks — previously matched the first occurrence and reset advancement,
/// and playing a queued interlude lost the era position entirely.
nonisolated struct PlaybackQueueLogic {
    /// What the engine should load next, with the display metadata that
    /// travels along.
    struct Target: Hashable, Sendable {
        let version: SongVersion
        let artistName: String
        let eraName: String
        let artUrl: String
        let artistSlug: String
    }

    enum Advance: Hashable, Sendable {
        case play(Target)
        case restart  // seek current track to 0
        case stop
    }

    private(set) var queue: [QueueItem] = []
    private(set) var eraSongs: EraSongContext?
    private(set) var playbackList: [PlaybackListItem]?
    /// Ordered era lists, one per artist. Keyed rather than kept in a single
    /// slot because `ArtistView` registers on every appearance: browsing B
    /// while A plays must not cost A its rollover, and must still leave B's
    /// list in place for when the user plays something from B.
    private var erasByArtist: [String: [EraSongContext]] = [:]

    /// The era list for whichever artist is currently playing.
    var artistEras: [EraSongContext] {
        eraSongs.map { erasByArtist[$0.artistName] ?? [] } ?? []
    }

    private var eraIndex: Int?   // position of eraSongs within its artist's list
    private var songIndex: Int?  // position within eraSongs.versions
    private var listIndex: Int?  // position within playbackList
    private var queueIdCounter = 0

    // MARK: - Context

    /// Position of an era inside its artist's registered list.
    ///
    /// Identity is (era name, artist, art URL). The version count is only a
    /// tiebreaker between eras that are otherwise identical — never a
    /// requirement, because the context usually arrives filtered while the
    /// registered list is not. See
    /// DECISIONS.md::PlaybackQueueLogic.swift::era-identity.
    private static func indexOfEra(_ context: EraSongContext, in eras: [EraSongContext]) -> Int? {
        let matches = eras.indices.filter { i in
            eras[i].eraName == context.eraName
                && eras[i].artistName == context.artistName
                && eras[i].artUrl == context.artUrl
        }
        guard matches.count > 1 else { return matches.first }
        return matches.first { eras[$0].versions.count == context.versions.count } ?? matches.first
    }

    /// Register the era context. Resolves its position inside `artistEras`
    /// by multi-field match so two eras sharing a name still disambiguate.
    mutating func setEraSongs(_ context: EraSongContext) {
        playbackList = nil
        listIndex = nil
        eraSongs = context
        songIndex = nil
        eraIndex = Self.indexOfEra(context, in: erasByArtist[context.artistName] ?? [])
    }

    /// Set the era context and position the cursor at `version`. Full-struct
    /// equality disambiguates duplicate (name, tag) pairs — byte-identical
    /// duplicates are interchangeable, so first match is fine there.
    mutating func playInEra(_ version: SongVersion, context: EraSongContext) -> Target? {
        setEraSongs(context)
        songIndex = context.versions.firstIndex(of: version)
        return Target(
            version: version,
            artistName: context.artistName,
            eraName: context.eraName,
            artUrl: context.artUrl,
            artistSlug: context.artistSlug ?? ""
        )
    }

    /// Start an ad-hoc list at `index`. Auto-advance walks the list and
    /// stops at its end — no rollover into other collections.
    mutating func playInList(_ items: [PlaybackListItem], startAt index: Int) -> Target? {
        guard items.indices.contains(index) else { return nil }
        playbackList = items
        listIndex = index
        eraSongs = nil
        songIndex = nil
        eraIndex = nil
        return Self.target(for: items[index])
    }

    /// Register an artist's ordered era list. Filed under that artist, so
    /// registering one never disturbs another's rollover — and an artist
    /// browsed mid-playback still has its list ready when the user plays it.
    mutating func setArtistEras(_ eras: [EraSongContext]) {
        guard let artist = eras.first?.artistName else { return }
        erasByArtist[artist] = eras
        registrationOrder.removeAll { $0 == artist }
        registrationOrder.append(artist)
        // Every entry holds every streamable version of every era, so a long
        // browsing session would otherwise accumulate whole trackers (Ye alone
        // is ~9k versions). Keep the few that can still matter: the playing
        // artist, plus the most recent registrations.
        while registrationOrder.count > Self.maxRetainedArtists {
            let evicted = registrationOrder.removeFirst()
            if evicted != eraSongs?.artistName {
                erasByArtist[evicted] = nil
            } else {
                registrationOrder.append(evicted)  // never evict what's playing
                break
            }
        }
        // Positions into the old array are meaningless — but only for the
        // artist whose list just changed.
        if eraSongs?.artistName == artist {
            eraIndex = nil
        }
    }

    private static let maxRetainedArtists = 4
    private var registrationOrder: [String] = []

    /// Drop the era/list contexts (playback stopped). The user queue and
    /// artist era list survive — they describe intent, not position.
    mutating func clearContexts() {
        eraSongs = nil
        playbackList = nil
        songIndex = nil
        listIndex = nil
        eraIndex = nil
    }

    // MARK: - Queue

    mutating func addToQueue(_ version: SongVersion, artistName: String, eraName: String, artUrl: String, artistSlug: String = "") {
        guard queue.count < 200 else { return }
        queueIdCounter += 1
        queue.append(QueueItem(
            id: queueIdCounter,
            version: version,
            artistName: artistName,
            eraName: eraName,
            artUrl: artUrl,
            artistSlug: artistSlug
        ))
    }

    mutating func removeFromQueue(at index: Int) {
        guard queue.indices.contains(index) else { return }
        queue.remove(at: index)
    }

    mutating func clearQueue() {
        queue.removeAll()
    }

    /// Reorder queue items. Mirrors SwiftUI's `move(fromOffsets:toOffset:)`
    /// semantics (destination expressed in pre-removal coordinates) without
    /// importing SwiftUI into this pure logic type.
    mutating func moveInQueue(from source: IndexSet, to destination: Int) {
        let moving = source.sorted().compactMap { queue.indices.contains($0) ? queue[$0] : nil }
        guard !moving.isEmpty else { return }
        let movingIds = Set(moving.map(\.id))
        let insertAt = queue.prefix(min(destination, queue.count))
            .filter { !movingIds.contains($0.id) }
            .count
        var remaining = queue.filter { !movingIds.contains($0.id) }
        remaining.insert(contentsOf: moving, at: min(insertAt, remaining.count))
        queue = remaining
    }

    /// Dequeue and return the item at `index`. Era/list cursors are left
    /// untouched: when the queue drains, auto-advance resumes exactly where
    /// the previous context left off.
    mutating func playFromQueue(at index: Int) -> Target? {
        guard queue.indices.contains(index) else { return nil }
        let item = queue.remove(at: index)
        return Target(
            version: item.version,
            artistName: item.artistName,
            eraName: item.eraName,
            artUrl: item.artUrl,
            artistSlug: item.artistSlug
        )
    }

    // MARK: - Advance

    mutating func next() -> Advance {
        // 1. The user queue always wins.
        if !queue.isEmpty, let target = playFromQueue(at: 0) {
            return .play(target)
        }

        // 2. Ad-hoc list — walk forward, stop at the end.
        if let list = playbackList {
            if let idx = listIndex, idx + 1 < list.count {
                listIndex = idx + 1
                return .play(Self.target(for: list[idx + 1]))
            }
            return .stop
        }

        // 3. Era context — next song, else roll into the next era with songs.
        guard let context = eraSongs else { return .stop }
        if let idx = songIndex, idx + 1 < context.versions.count {
            songIndex = idx + 1
            return .play(Self.target(for: context.versions[idx + 1], in: context))
        }
        if let nextEra = advanceToNextEra(after: context) {
            eraSongs = nextEra
            songIndex = 0
            if let first = nextEra.versions.first {
                return .play(Self.target(for: first, in: nextEra))
            }
        }
        return .stop
    }

    mutating func previous(currentTime: TimeInterval) -> Advance {
        // More than 3 seconds in → restart the current track.
        if currentTime > 3 { return .restart }

        if let list = playbackList {
            if let idx = listIndex, idx > 0, list.indices.contains(idx - 1) {
                listIndex = idx - 1
                return .play(Self.target(for: list[idx - 1]))
            }
            return .restart
        }

        if let context = eraSongs, let idx = songIndex, idx > 0,
           context.versions.indices.contains(idx - 1) {
            songIndex = idx - 1
            return .play(Self.target(for: context.versions[idx - 1], in: context))
        }
        return .restart
    }

    /// Next era after the current one that has any versions. Prefers the
    /// recorded position (survives duplicate era names); falls back to the same
    /// identity match `setEraSongs` uses when the position is unset
    /// (setArtistEras ran after setEraSongs).
    private mutating func advanceToNextEra(after current: EraSongContext) -> EraSongContext? {
        let eras = erasByArtist[current.artistName] ?? []
        let startIdx: Int
        if let idx = eraIndex, eras.indices.contains(idx) {
            startIdx = idx + 1
        } else if let idx = Self.indexOfEra(current, in: eras) {
            startIdx = idx + 1
        } else {
            return nil
        }
        for idx in startIdx..<eras.count where !eras[idx].versions.isEmpty {
            eraIndex = idx
            return eras[idx]
        }
        return nil
    }

    // MARK: - Helpers

    private static func target(for item: PlaybackListItem) -> Target {
        Target(
            version: item.version,
            artistName: item.artistName,
            eraName: item.eraName,
            artUrl: item.artUrl,
            artistSlug: item.artistSlug ?? ""
        )
    }

    private static func target(for version: SongVersion, in context: EraSongContext) -> Target {
        Target(
            version: version,
            artistName: context.artistName,
            eraName: context.eraName,
            artUrl: context.artUrl,
            artistSlug: context.artistSlug ?? ""
        )
    }
}
