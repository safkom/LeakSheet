import Foundation

/// Resolves file-sharing links to stream proxy URLs.
///
/// One `URLComponents` parse plus host/path checks, not regex: `Regex` isn't
/// `Sendable` (so can't be a static), and `isStreamable` is a hot path.
enum StreamResolver {
    /// What a supported link points at.
    nonisolated enum Target: Equatable, Sendable {
        case pillows(id: String)
        case imgur(id: String)
        case froste(hash: String)
        case kraken
        case pixeldrain(id: String)
        case gdrive
    }

    /// Characters a provider id may contain; pixeldrain ids are alphanumeric only.
    private nonisolated static func isIDChar(_ char: Character, allowsSeparators: Bool) -> Bool {
        char.isASCII && (char.isLetter || char.isNumber || (allowsSeparators && (char == "_" || char == "-")))
    }

    private nonisolated static func isID(_ text: String, allowsSeparators: Bool = true) -> Bool {
        !text.isEmpty && text.allSatisfy { isIDChar($0, allowsSeparators: allowsSeparators) }
    }

    /// The id a path segment starts with, as the backend's patterns take it: what follows
    /// (`.mp3`, `)`, a second link) never changes the file. Empty when the segment doesn't start with one.
    private nonisolated static func idPrefix(_ text: String, allowsSeparators: Bool = true) -> Substring {
        text.prefix { isIDChar($0, allowsSeparators: allowsSeparators) }
    }

    private nonisolated static func hasLineBreakOrTab(_ text: String) -> Bool {
        text.unicodeScalars.contains { $0 == "\t" || $0 == "\r" || $0 == "\n" }
    }

    private nonisolated static func isHex(_ text: String) -> Bool {
        !text.isEmpty && text.allSatisfy { $0.isASCII && $0.isHexDigit }
    }

    /// The backend reads the authority literally: no userinfo or port, and Foundation's folding of
    /// look-alikes (`ſ`, the Kelvin sign) onto ASCII doesn't count. Only host characters pass.
    private nonisolated static func hasPlainAuthority(_ link: String) -> Bool {
        guard let sep = link.range(of: "://") else { return false }
        return link[sep.upperBound...].prefix { !"/?#".contains($0) }
            .allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }
    }

    /// Query keys Google Docs glues onto every link it rewrites through its redirector:
    /// not part of the file URL, and the sheet parser carries them through verbatim.
    private nonisolated static let googleWrapperKeys: Set<String> = [
        "sa", "source", "ust", "usg", "ved"
    ]

    /// A link with Google's redirect tracking removed, so it isn't nested into `/stream?url=`.
    ///
    /// The params can be glued onto the path with no `?` (`/f/{id}&sa=D&…`). Only strips when
    /// EVERY trailing `&key=value` pair is a known wrapper key.
    nonisolated static func canonical(_ link: String) -> String {
        guard let marker = link.range(of: "&sa=") else { return link }
        let tail = link[marker.lowerBound...].dropFirst()
        let keys = tail.split(separator: "&").compactMap {
            $0.split(separator: "=", maxSplits: 1).first.map(String.init)
        }
        guard !keys.isEmpty, keys.allSatisfy(googleWrapperKeys.contains) else { return link }
        return String(link[..<marker.lowerBound])
    }

    /// Classify a link. Trailing path segments are ignored, so
    /// `/file/d/{id}/view?usp=sharing` still resolves. Segments are read percent-encoded: the
    /// backend's patterns are literal, so `/f/%61bc` is not `/f/abc`.
    nonisolated static func target(for rawLink: String) -> Target? {
        let link = canonical(rawLink)
        guard hasPlainAuthority(link), let comps = URLComponents(string: link),
              let scheme = comps.scheme?.lowercased(), scheme == "http" || scheme == "https",
              var host = comps.host?.lowercased()
        else { return nil }
        let hasWWW = host.hasPrefix("www.")
        if hasWWW { host = String(host.dropFirst(4)) }

        // Empty segments stay: the backend's patterns need the literal /f/{id} shape.
        let path = comps.percentEncodedPath.split(
            separator: "/",
            omittingEmptySubsequences: false
        ).dropFirst().map(String.init)
        return hostResolvers[host]?(LinkParts(path: path, comps: comps, hasWWW: hasWWW, rawLink: rawLink))
    }

    /// The pieces of a link a host's resolver reads.
    private nonisolated struct LinkParts: Sendable {
        let path: [String]
        let comps: URLComponents
        let hasWWW: Bool
        let rawLink: String

        /// The id after a `/{segment}/` prefix, or "" when the path has another shape.
        func id(after segment: String, allowsSeparators: Bool = true) -> String {
            guard path.count >= 2, path[0].lowercased() == segment else { return "" }
            return String(StreamResolver.idPrefix(path[1], allowsSeparators: allowsSeparators))
        }
    }

    private nonisolated static let hostResolvers: [String: @Sendable (LinkParts) -> Target?] = {
        let pillows: @Sendable (LinkParts) -> Target? = { link in
            let id = link.id(after: "f")
            return id.isEmpty ? nil : .pillows(id: id)
        }
        let imgur: @Sendable (LinkParts) -> Target? = { link in
            let id = link.id(after: "f")
            return id.isEmpty ? nil : .imgur(id: id)
        }
        return [
            "pillows.su": pillows, "pillowcase.su": pillows, "plwcse.top": pillows,
            "imgur.gg": imgur, "temp.imgur.gg": imgur,
            "music.froste.lol": froste,
            "krakenfiles.com": kraken,
            "pixeldrain.com": { link in
                // /u/ is a single file; /l/ is a list and stays unresolved.
                let id = link.id(after: "u", allowsSeparators: false)
                return id.isEmpty ? nil : .pixeldrain(id: id)
            },
            "drive.google.com": gdrive
        ]
    }()

    /// The backend's froste pattern has no www. form, unlike every other host. Like the
    /// backend, the hash is a whole alphanumeric run: `0123abcdzz` is no hex prefix.
    private nonisolated static func froste(_ link: LinkParts) -> Target? {
        guard !link.hasWWW else { return nil }
        let hash = link.id(after: "song", allowsSeparators: false)
        return isHex(hash) ? .froste(hash: hash) : nil
    }

    /// The view page itself is the target; the backend scrapes its CDN URL.
    private nonisolated static func kraken(_ link: LinkParts) -> Target? {
        let path = link.path
        guard path.count >= 3, path[0].lowercased() == "view",
              isID(path[1]), path[2].lowercased().hasPrefix("file.html") else { return nil }
        return .kraken
    }

    /// The three forms the backend resolves (streaming._extract_gdrive_id): /file/d/{id},
    /// /open?id=, /uc?id=. Folders carry no file id.
    private nonisolated static func gdrive(_ link: LinkParts) -> Target? {
        let path = link.path
        if path.count >= 3, path[0].lowercased() == "file", path[1].lowercased() == "d",
           !idPrefix(path[2]).isEmpty {
            return .gdrive
        }
        // Python refuses a link with a tab/CR/LF in it (urlsplit would drop it), and its
        // parse_qs drops blank values, so the first NON-empty id is the one.
        guard !hasLineBreakOrTab(link.rawLink),
              ["/open", "/uc"].contains(link.comps.percentEncodedPath.lowercased()),
              let id = link.comps.queryItems?.first(where: { $0.name == "id" && $0.value?.isEmpty == false })?.value
        else { return nil }
        return isID(id) ? .gdrive : nil
    }

    /// The backend's provider key for a link, as `GET /hosts` names it.
    nonisolated static func provider(for link: String) -> String? {
        switch target(for: link) {
        case .pillows: return "pillows"
        case .imgur: return "imgur"
        case .froste: return "froste"
        case .kraken: return "kraken"
        case .pixeldrain: return "pixeldrain"
        case .gdrive: return "gdrive"
        case nil: return nil
        }
    }

    nonisolated static func isStreamableURL(_ url: String) -> Bool {
        target(for: url) != nil
    }

    /// Returns the proxied stream URL for a file-sharing link.
    nonisolated static func streamURL(for originalLink: String) -> URL? {
        // Nested as the VALUE of the backend's `url=` parameter: see `leakSheetURLValue`.
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

        case .froste:
            // The download endpoint needs a Referer, which only the backend proxy sends.
            return streamURL(for: originalLink)

        case .imgur:
            // The /f/{id} link is an HTML page; only imgur's API, which the backend proxy
            // calls, knows the CDN URL.
            return streamURL(for: originalLink)

        case .kraken:
            // The view URL is an HTML page; the backend proxy scrapes the CDN URL and streams
            // the original bytes, so "original quality" IS the proxied stream.
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
    nonisolated static let leakSheetURLValue = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )
}
