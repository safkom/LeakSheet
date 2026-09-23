import SwiftUI

/// Owns the tracker-loading pipeline: conditional fetch, ETag/304 replay from the
/// local cache, recents bookkeeping, and friendly error mapping. Shared by the iOS
/// landing screen and the macOS sidebar panes so loading behaviour can't diverge.
@MainActor
@Observable
final class TrackerLoader {
    var url: String = ""
    private(set) var loading = false
    private(set) var loadPhase: APIClient.LoadPhase?
    private(set) var error: String?
    /// Set when the returned tracker came from the local cache because the server was
    /// unreachable: the content is usable, but a failed refresh must not look successful.
    private(set) var staleNotice: String?

    /// Loads and parses a tracker. Returns the parsed artist, or nil if the load
    /// failed (`error` then carries a user-facing message).
    ///
    /// `forceRefresh` skips the conditional request so the backend re-parses rather
    /// than answering 304. The result is still cached.
    func load(
        _ urlString: String,
        artistName: String? = nil,
        forceRefresh: Bool = false,
        recents: RecentTrackersManager
    ) async -> Artist? {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        // A tracker keeps the name it was first opened under, whichever entry point
        // reopens it: see DECISIONS.md::TrackerLoader.swift::sticky-artist-name.
        let resolvedName = artistName ?? recents.savedName(forSourceUrl: trimmed)
        // One load at a time, across every call site: concurrent loads raced into
        // multiple navigation pushes.
        guard !loading else { return nil }
        withAnimation { error = nil }
        staleNotice = nil
        loading = true
        loadPhase = nil
        defer {
            loading = false
            loadPhase = nil
        }

        // Conditional request: send the cached ETag (a sidecar read) so an unchanged
        // tracker comes back as a bodyless 304 and the local copy reopens.
        var cachedEtag: String?
        if !forceRefresh {
            loadPhase = .readingCache
            cachedEtag = await CacheService.shared.getCachedEtag(for: trimmed)
        }

        do {
            let result = try await APIClient.shared.parseSheet(
                url: trimmed,
                artistName: resolvedName,
                forceRefresh: forceRefresh,
                cachedEtag: cachedEtag,
                onProgress: { @Sendable phase in
                    // `publish` serialises phases, so a late .downloading can't follow .preparing.
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
                return await replayFromCache(trimmed, artistName: resolvedName, recents: recents)
            case .httpError(let status, let msg):
                // 5xx only. A 4xx is the server answering ABOUT this tracker (404/410 gone, 403
                // refused); serving the cached copy would hide that forever.
                if status >= 500,
                   let cached = await offlineFallback(trimmed, artistName: resolvedName, recents: recents) {
                    return cached
                }
                withAnimation { error = Self.friendlyLoadError(status: status, fallback: msg) }
            case .invalidURL:
                withAnimation { error = "Invalid URL" }
            }
        } catch let urlError as URLError where urlError.code == .timedOut {
            if let cached = await offlineFallback(trimmed, artistName: resolvedName, recents: recents) {
                return cached
            }
            withAnimation { error = "This tracker is taking a while to load. Please try again." }
        } catch is DecodingError {
            // The server answered, but with data this build can't read. Not
            // an outage, so don't say "couldn't reach the server".
            if let cached = await cachedFallback(trimmed, artistName: resolvedName, recents: recents) {
                staleNotice = "Couldn't read the latest data — showing the last saved copy."
                return cached
            }
            withAnimation { error = "This tracker's data couldn't be read. The app may need an update." }
        } catch is CancellationError {
            // The user navigated away: not a failure to recover from, and a fallback would
            // write a recents entry for an abandoned tracker.
            return nil
        } catch let urlError as URLError where urlError.code == .cancelled {
            return nil
        } catch {
            if let cached = await offlineFallback(trimmed, artistName: resolvedName, recents: recents) {
                return cached
            }
            withAnimation { self.error = error.localizedDescription }
        }
        return nil
    }

    /// `cachedFallback` for the failure paths: same lookup, but it marks the
    /// result stale. The 304 path uses the bare lookup instead — there the
    /// server confirmed the copy is current, so there is nothing to warn about.
    private func offlineFallback(
        _ trimmed: String,
        artistName: String?,
        recents: RecentTrackersManager
    ) async -> Artist? {
        guard let cached = await cachedFallback(trimmed, artistName: artistName, recents: recents) else {
            return nil
        }
        staleNotice = "Couldn't reach the server — showing the last saved copy."
        return cached
    }

    /// A previously-cached tracker stays usable when the network is down (hard
    /// failures only; the 304 path has `replayFromCache`). A copy cached under a
    /// different name carries a different slug, so it is not returned.
    private func cachedFallback(
        _ trimmed: String,
        artistName: String?,
        recents: RecentTrackersManager
    ) async -> Artist? {
        guard let cachedArtist = await CacheService.shared.getCachedArtist(for: trimmed),
              artistName == nil || artistName == cachedArtist.name else { return nil }
        recents.saveTracker(artist: cachedArtist)
        return cachedArtist
    }

    /// Hold the loading state up while the caller finishes the job: building the view
    /// model and warming the first era covers. Keeps the concurrent-load guard armed.
    func preparing<T>(_ body: () async -> T) async -> T {
        loading = true
        loadPhase = .preparing
        defer {
            loading = false
            loadPhase = nil
        }
        return await body()
    }

    /// Ordered hand-off of a progress phase onto the main actor, so a late
    /// `.downloading` can't land after `.preparing` and rewind the label.
    private nonisolated static func publish(_ phase: APIClient.LoadPhase, to loader: TrackerLoader) {
        Task { @MainActor in loader.apply(phase) }
    }

    /// Monotonic: a phase never moves backwards within one load.
    private func apply(_ phase: APIClient.LoadPhase) {
        guard Self.rank(phase) >= Self.rank(loadPhase) else { return }
        // Rank alone doesn't order two `.downloading` updates — they tie — so
        // a chunk callback landing late could still rewind the byte counter.
        if case .downloading(let newBytes, _) = phase,
           case .downloading(let shownBytes, _) = loadPhase,
           newBytes < shownBytes {
            return
        }
        loadPhase = phase
    }

    static func rank(_ phase: APIClient.LoadPhase?) -> Int {
        switch phase {
        case nil: return -1
        case .readingCache: return 0
        case .connecting: return 1
        // Every server message shares one rank, so a later message replaces an
        // earlier one but can never follow the download.
        case .server: return 2
        case .downloading: return 3
        case .preparing: return 4
        }
    }

    /// 304 path: reopen the local copy, or refetch unconditionally if the ETag matched
    /// but the cached payload is gone. Reports progress through the decode and build.
    private func replayFromCache(
        _ trimmed: String,
        artistName: String?,
        recents: RecentTrackersManager
    ) async -> Artist? {
        loadPhase = .preparing
        // A copy cached under a DIFFERENT name carries a different slug (the favourites
        // key), so drop it and refetch under the resolved name.
        if let cachedArtist = await cachedFallback(trimmed, artistName: artistName, recents: recents) {
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

    /// Maps a backend HTTP failure to a plain, actionable message: a big tracker can
    /// hit the gateway timeout on a cold parse, and "HTTP 504" means nothing to a user.
    ///
    /// A 502/503 carrying the server's own message ("Could not reach the tracker
    /// source.") shows it. `fallback` is `APIClient.bareStatusMessage` otherwise.
    nonisolated static func friendlyLoadError(status: Int, fallback: String) -> String {
        if status == 502 || status == 503, fallback != APIClient.bareStatusMessage(status) {
            return fallback
        }
        switch status {
        case 502, 503, 504, 524:  // 524: Cloudflare's origin timeout
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
