import Foundation

/// Resolves file-sharing links to stream proxy URLs.
///
/// Implemented with a single `URLComponents` parse plus host/path checks
/// rather than regex. `Regex` is not `Sendable`, so the patterns could not be
/// hoisted into statics and were rebuilt on *every* call — and this is a hot
/// path: `isStreamable` runs per version inside the era-stats and filter
/// passes (a big tab carries ~1900 entries), where the common case is a
/// non-matching host that had to fall through all seven patterns.
enum StreamResolver {
    /// What a supported link points at. Parsing once and switching on the
    /// result replaces six sequential match attempts per URL.
    nonisolated enum Target: Equatable, Sendable {
        case pillows(id: String)
        case imgur(id: String)
        case froste(hash: String)
        case kraken
        case pixeldrain(id: String)
        case gdrive
    }

    /// Characters a provider id may contain. Matches the previous regex
    /// classes exactly — pixeldrain ids are alphanumeric only.
    private nonisolated static func isID(_ s: String, allowsSeparators: Bool = true) -> Bool {
        !s.isEmpty && s.allSatisfy { ch in
            ch.isASCII && (ch.isLetter || ch.isNumber || (allowsSeparators && (ch == "_" || ch == "-")))
        }
    }

    private nonisolated static func isHex(_ s: String) -> Bool {
        !s.isEmpty && s.allSatisfy(\.isHexDigit)
    }

    /// Query keys Google Docs glues onto every link it rewrites through its
    /// redirector. They are not part of the file URL, and the sheet parser
    /// carries them through verbatim.
    private nonisolated static let googleWrapperKeys: Set<String> = [
        "sa", "source", "ust", "usg", "ved",
    ]

    /// A link with Google's redirect tracking removed.
    ///
    /// Two shapes reach us. On Drive links the params sit in a real query
    /// (`open?id=X&usp=…&sa=D&…`), which classification already ignored. On
    /// pillows links they are glued straight onto the path with no `?` at all
    /// (`/f/{id}&sa=D&source=editors&…`), which made the id fail `isID` — so
    /// 25 links in the live corpus carried no play affordance at all.
    ///
    /// Only strips when EVERY trailing `&key=value` pair is a known wrapper
    /// key, so a genuine multi-param link is left alone.
    nonisolated static func canonical(_ link: String) -> String {
        guard let marker = link.range(of: "&sa=") else { return link }
        let tail = link[marker.lowerBound...].dropFirst()
        let keys = tail.split(separator: "&").compactMap {
            $0.split(separator: "=", maxSplits: 1).first.map(String.init)
        }
        guard !keys.isEmpty, keys.allSatisfy(googleWrapperKeys.contains) else { return link }
        return String(link[..<marker.lowerBound])
    }

    /// Classify a link. Trailing path segments are ignored the way the old
    /// patterns did (they matched an id followed by `/`, `?`, `#`, or end),
    /// so `/file/d/{id}/view?usp=sharing` still resolves.
    nonisolated static func target(for link: String) -> Target? {
        guard let comps = URLComponents(string: canonical(link)),
              let scheme = comps.scheme?.lowercased(), scheme == "http" || scheme == "https",
              var host = comps.host?.lowercased()
        else { return nil }
        if host.hasPrefix("www.") { host = String(host.dropFirst(4)) }

        let path = comps.path.split(separator: "/").map(String.init)

        switch host {
        case "pillows.su", "pillowcase.su":
            guard path.count >= 2, path[0].lowercased() == "f", isID(path[1]) else { return nil }
            return .pillows(id: path[1])

        case "imgur.gg", "temp.imgur.gg":
            guard path.count >= 2, path[0].lowercased() == "f", isID(path[1]) else { return nil }
            return .imgur(id: path[1])

        case "music.froste.lol":
            guard path.count >= 2, path[0].lowercased() == "song", isHex(path[1]) else { return nil }
            return .froste(hash: path[1])

        case "krakenfiles.com":
            // The view page itself is the target; the backend scrapes its CDN URL.
            guard path.count >= 3, path[0].lowercased() == "view",
                  isID(path[1]), path[2].lowercased() == "file.html" else { return nil }
            return .kraken

        case "pixeldrain.com":
            // /u/ is a single file; /l/ is a list and stays unresolved.
            guard path.count >= 2, path[0].lowercased() == "u",
                  isID(path[1], allowsSeparators: false) else { return nil }
            return .pixeldrain(id: path[1])

        case "drive.google.com":
            // The three forms the backend resolves (streaming._extract_gdrive_id):
            // /file/d/{id}, /open?id=, /uc?id=. Folders carry no file id.
            if path.count >= 3, path[0].lowercased() == "file", path[1].lowercased() == "d",
               isID(path[2]) {
                return .gdrive
            }
            if path.count >= 1, ["open", "uc"].contains(path[0].lowercased()),
               let id = comps.queryItems?.first(where: { $0.name.lowercased() == "id" })?.value,
               isID(id) {
                return .gdrive
            }
            return nil

        default:
            return nil
        }
    }

    nonisolated static func isStreamableURL(_ url: String) -> Bool {
        target(for: url) != nil
    }

    /// Returns the proxied stream URL for a file-sharing link.
    nonisolated static func streamURL(for originalLink: String) -> URL? {
        // `.urlQueryAllowed` leaves `&`, `=` and `?` unescaped, but the link is
        // nested as the VALUE of the backend's own `url=` parameter — so
        // everything after the first `&` arrived as separate top-level params
        // and the backend saw a truncated URL. Escape everything outside the
        // RFC 3986 unreserved set.
        let link = canonical(originalLink)
        guard isStreamableURL(link),
              let encoded = link.addingPercentEncoding(withAllowedCharacters: .leakSheetURLValue)
        else { return nil }
        return URL(string: "\(APIClient.baseURL)/stream?url=\(encoded)")
    }

    /// Returns the original-quality download URL for a file-sharing link.
    nonisolated static func originalQualityURL(for originalLink: String) -> URL? {
        switch target(for: canonical(originalLink)) {
        case .pillows(let id):
            return URL(string: "https://api.pillows.su/api/download/\(id)")

        case .froste(let hash):
            return URL(string: "https://music.froste.lol/song/\(hash)/download")

        case .imgur:
            // Same trap as kraken below: the /f/{id} link is an HTML page, and
            // the real CDN URL is only discoverable through imgur's API, which
            // the backend proxy already calls. Returning the page URL handed
            // AVPlayer HTML and failed with "Operation Stopped".
            return streamURL(for: originalLink)

        case .kraken:
            // The view URL is an HTML page — AVPlayer can't play it directly.
            // The backend proxy scrapes the CDN URL and streams the original
            // file bytes, so "original quality" IS the proxied stream here.
            return streamURL(for: originalLink)

        case .pixeldrain(let id):
            return URL(string: "https://pixeldrain.com/api/file/\(id)?download")

        case .gdrive:
            // Drive's direct download needs the proxy's interstitial handling.
            return streamURL(for: originalLink)

        case nil:
            return nil
        }
    }
}

extension CharacterSet {
    /// RFC 3986 unreserved characters. Anything else is escaped, which is what
    /// a URL nested inside another URL's query value requires — `.urlQueryAllowed`
    /// keeps sub-delimiters like `&` and `=` and would split the value in two.
    nonisolated(unsafe) static let leakSheetURLValue = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )
}
