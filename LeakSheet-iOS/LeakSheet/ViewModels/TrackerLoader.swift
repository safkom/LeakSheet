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

    func clearError() {
        withAnimation { error = nil }
    }

    /// Loads and parses a tracker. Returns the parsed artist, or nil if the
    /// load failed (in which case `error` carries a user-facing message).
    func load(
        _ urlString: String,
        artistName: String? = nil,
        recents: RecentTrackersManager
    ) async -> Artist? {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
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
        let cachedEtag = await CacheService.shared.getCachedEtag(for: trimmed)

        do {
            let result = try await APIClient.shared.parseSheet(
                url: trimmed,
                artistName: artistName,
                cachedEtag: cachedEtag,
                onProgress: { phase in
                    Task { @MainActor in self.loadPhase = phase }
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

    /// 304 path: reopen the local copy, or refetch unconditionally if the ETag
    /// matched but the cached payload is gone.
    private func replayFromCache(
        _ trimmed: String,
        artistName: String?,
        recents: RecentTrackersManager
    ) async -> Artist? {
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
