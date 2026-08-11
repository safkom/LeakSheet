import SwiftUI

/// Owns the tracker-loading pipeline: conditional fetch, ETag/304 replay from
/// the local cache, recents bookkeeping, and friendly error mapping.
///
/// Extracted from `LandingView` so the iOS landing screen and the macOS sidebar's
/// Browse and Recents panes share one implementation — the panes are laid out
/// differently per platform, but the loading behaviour must not diverge.
/// See DECISIONS.md::TrackerLoader.swift::extraction.
@MainActor
@Observable
final class TrackerLoader {
    var url: String = ""
    private(set) var loading = false
    private(set) var loadPhase: APIClient.LoadPhase?
    private(set) var error: String?

    /// Loads and parses a tracker. Returns the parsed artist, or nil if the
    /// load failed (in which case `error` carries a user-facing message).
    ///
    /// `forceRefresh` skips the conditional request so the backend re-parses
    /// rather than answering 304 — the "refresh this tracker" path. The result
    /// is still cached, so a refresh never leaves the tracker without a local
    /// copy for next time.
    func load(
        _ urlString: String,
        artistName: String? = nil,
        forceRefresh: Bool = false,
        recents: RecentTrackersManager
    ) async -> Artist? {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        // `loading` drove a spinner but gated nothing, and only the Parse
        // button was ever disabled — so tapping several recents/browse rows
        // started that many loads. They raced into multiple path.append calls,
        // and whichever finished first cleared `loading` via the defer below
        // while the others were still running. One guard here covers all six
        // call sites (iOS landing, recents, browse, macOS, tvOS ×2).
        guard !loading else { return nil }
        withAnimation { error = nil }
        loading = true
        loadPhase = nil
        defer {
            loading = false
            loadPhase = nil
        }

        // Conditional request: send the cached ETag so an unchanged tracker
        // comes back as a bodyless 304 and we reopen the local copy instead
        // of re-downloading and re-decoding the full multi-MB payload.
        // Reads the sidecar, not the payload — see CacheService.getCachedMeta.
        var cachedEtag: String?
        if !forceRefresh {
            loadPhase = .readingCache
            cachedEtag = await CacheService.shared.getCachedEtag(for: trimmed)
        }

        do {
            let result = try await APIClient.shared.parseSheet(
                url: trimmed,
                artistName: artistName,
                forceRefresh: forceRefresh,
                cachedEtag: cachedEtag,
                onProgress: { @Sendable phase in
                    // Hopped through one MainActor.assumeIsolated-free Task per
                    // callback before; that gave no ordering guarantee between
                    // a late .downloading and .preparing. `publish` serialises.
                    Self.publish(phase, to: self)
                }
            )
            if let etag = result.etag {
                await CacheService.shared.cacheTracker(url: trimmed, data: result.rawData, etag: etag)
            }
            recents.saveTracker(artist: result.artist)
            return result.artist
        } catch let apiError as APIError {
            switch apiError {
            case .notModified:
                return await replayFromCache(trimmed, artistName: artistName, recents: recents)
            case .httpError(let status, let msg):
                withAnimation { error = Self.friendlyLoadError(status: status, fallback: msg) }
            case .invalidURL:
                withAnimation { error = "Invalid URL" }
            }
        } catch let urlError as URLError where urlError.code == .timedOut {
            withAnimation { error = "This tracker is taking a while to load. Please try again." }
        } catch {
            withAnimation { self.error = error.localizedDescription }
        }
        return nil
    }

    /// Hold the loading state up while the caller finishes the job — building
    /// the view model and warming the first era covers.
    ///
    /// `load` clears `loading` on return, so that work (the slowest part of a
    /// big tracker) previously ran with no indicator at all, and the artist
    /// screen answered with its own second "Preparing…" spinner. Keeping
    /// `loading` true here also keeps the concurrent-load guard armed.
    func preparing<T>(_ body: () async -> T) async -> T {
        loading = true
        loadPhase = .preparing
        defer {
            loading = false
            loadPhase = nil
        }
        return await body()
    }

    /// Ordered hand-off of a progress phase onto the main actor.
    ///
    /// Each callback used to spawn its own unstructured `Task { @MainActor }`,
    /// one per 256KB chunk, with no ordering between them — a late
    /// `.downloading` could land after `.preparing` and rewind the label.
    private nonisolated static func publish(_ phase: APIClient.LoadPhase, to loader: TrackerLoader) {
        Task { @MainActor in loader.apply(phase) }
    }

    /// Monotonic: a phase never moves backwards within one load.
    private func apply(_ phase: APIClient.LoadPhase) {
        guard Self.rank(phase) >= Self.rank(loadPhase) else { return }
        loadPhase = phase
    }

    static func rank(_ phase: APIClient.LoadPhase?) -> Int {
        switch phase {
        case nil: return -1
        case .readingCache: return 0
        case .connecting: return 1
        case .downloading: return 2
        case .preparing: return 3
        }
    }

    /// 304 path: reopen the local copy, or refetch unconditionally if the ETag
    /// matched but the cached payload is gone.
    ///
    /// This is the *common* path for a returning user, and it used to report
    /// nothing at all: parseSheet throws before reaching `.preparing`, so the
    /// UI sat on "Contacting server…" through a multi-MB decode and the whole
    /// view-model build. Both are announced now.
    private func replayFromCache(
        _ trimmed: String,
        artistName: String?,
        recents: RecentTrackersManager
    ) async -> Artist? {
        loadPhase = .preparing
        if let cachedArtist = await CacheService.shared.getCachedArtist(for: trimmed) {
            recents.saveTracker(artist: cachedArtist)
            return cachedArtist
        }
        await CacheService.shared.removeTracker(for: trimmed)
        do {
            let result = try await APIClient.shared.parseSheet(url: trimmed, artistName: artistName)
            if let etag = result.etag {
                await CacheService.shared.cacheTracker(url: trimmed, data: result.rawData, etag: etag)
            }
            recents.saveTracker(artist: result.artist)
            return result.artist
        } catch {
            withAnimation { self.error = "Failed to load tracker" }
            return nil
        }
    }

    /// Maps a backend HTTP failure to a plain, actionable message. Big trackers
    /// (e.g. Ye) can exceed the gateway timeout on a cold parse and return 5xx —
    /// a raw "HTTP 504" means nothing to a user, so say what to do instead.
    static func friendlyLoadError(status: Int, fallback: String) -> String {
        switch status {
        case 502, 503, 504:
            return "This tracker is large and the server timed out. Please try again."
        case 500:
            return "The server couldn't parse this tracker. Please try again."
        case 404:
            return "Tracker not found. Check the link and try again."
        default:
            return fallback
        }
    }
}
