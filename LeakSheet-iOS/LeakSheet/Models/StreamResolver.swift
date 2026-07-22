import Foundation

/// Resolves file-sharing links to stream proxy URLs.
///
/// Patterns are compile-checked Swift regex literals — an invalid pattern is
/// a build error, not a runtime crash. They live inside the match functions
/// because `Regex` is not `Sendable` and so can't be a nonisolated static.
enum StreamResolver {
    nonisolated private static func pillowsID(_ url: String) -> Substring? {
        url.firstMatch(
            of: #/^https?://(?:www\.)?(?:pillows\.su|pillowcase\.su)/f/([A-Za-z0-9_-]+)(?:$|[?#/])/#
                .ignoresCase()
        )?.1
    }

    nonisolated private static func imgurID(_ url: String) -> Substring? {
        url.firstMatch(
            of: #/^https?://(?:www\.)?(?:temp\.)?imgur\.gg/f/([A-Za-z0-9_-]+)(?:$|[?#/])/#
                .ignoresCase()
        )?.1
    }

    nonisolated private static func frosteHash(_ url: String) -> Substring? {
        url.firstMatch(
            of: #/^https?://music\.froste\.lol/song/([a-f0-9]+)(?:$|[?#/])/#
                .ignoresCase()
        )?.1
    }

    nonisolated private static func isKrakenView(_ url: String) -> Bool {
        url.firstMatch(
            of: #/^https?://(?:www\.)?krakenfiles\.com/view/[A-Za-z0-9_-]+/file\.html(?:$|[?#])/#
                .ignoresCase()
        ) != nil
    }

    /// pixeldrain single files only — /l/ lists are collections and open
    /// externally.
    nonisolated private static func pixeldrainID(_ url: String) -> Substring? {
        url.firstMatch(
            of: #/^https?://(?:www\.)?pixeldrain\.com/u/([A-Za-z0-9]+)(?:$|[?#/])/#
                .ignoresCase()
        )?.1
    }

    /// Google Drive single-file links. Matches the three forms the backend
    /// resolves (`streaming._extract_gdrive_id`): `/file/d/{id}`, `/open?id=`,
    /// and `/uc?id=`. Keeping this in sync means a Drive audio link classifies
    /// and plays the same in-app as it does through the backend proxy — folders
    /// (no file id) still stay unresolved.
    nonisolated private static func gdriveFileID(_ url: String) -> Substring? {
        if let m = url.firstMatch(
            of: #/^https?://(?:www\.)?drive\.google\.com/file/d/([A-Za-z0-9_-]+)(?:$|[?#/])/#
                .ignoresCase()
        ) {
            return m.1
        }
        // open?id={id} / uc?id={id} — the id can sit alongside other params.
        return url.firstMatch(
            of: #/^https?://(?:www\.)?drive\.google\.com/(?:open|uc)\?(?:[^#]*&)?id=([A-Za-z0-9_-]+)/#
                .ignoresCase()
        )?.1
    }

    nonisolated static func isStreamableURL(_ url: String) -> Bool {
        pillowsID(url) != nil
            || imgurID(url) != nil
            || frosteHash(url) != nil
            || isKrakenView(url)
            || pixeldrainID(url) != nil
            || gdriveFileID(url) != nil
    }

    /// Returns the proxied stream URL for a file-sharing link.
    nonisolated static func streamURL(for originalLink: String) -> URL? {
        guard isStreamableURL(originalLink),
              let encoded = originalLink.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed)
        else { return nil }
        return URL(string: "\(APIClient.baseURL)/stream?url=\(encoded)")
    }

    /// Returns the original-quality download URL for a file-sharing link.
    nonisolated static func originalQualityURL(for originalLink: String) -> URL? {
        if let id = pillowsID(originalLink) {
            return URL(string: "https://api.pillows.su/api/download/\(id)")
        }

        if let hash = frosteHash(originalLink) {
            return URL(string: "https://music.froste.lol/song/\(hash)/download")
        }

        if imgurID(originalLink) != nil {
            return URL(string: originalLink)
        }

        if isKrakenView(originalLink) {
            // The view URL is an HTML page — AVPlayer can't play it directly.
            // The backend proxy scrapes the CDN URL and streams the original
            // file bytes, so "original quality" IS the proxied stream here.
            return streamURL(for: originalLink)
        }

        if let id = pixeldrainID(originalLink) {
            return URL(string: "https://pixeldrain.com/api/file/\(id)?download")
        }

        if gdriveFileID(originalLink) != nil {
            // Drive's direct download needs the proxy's interstitial handling.
            return streamURL(for: originalLink)
        }

        return nil
    }
}
