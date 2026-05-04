import Foundation

/// Resolves file-sharing links to stream proxy URLs.
///
enum StreamResolver {
    nonisolated private static func compile(_ pattern: String) -> NSRegularExpression {
        do {
            return try NSRegularExpression(pattern: pattern, options: .caseInsensitive)
        } catch {
            fatalError("StreamResolver: invalid regex /\(pattern)/ — \(error)")
        }
    }

    nonisolated private static let pillowsPattern = compile(
        #"^https?://(?:www\.)?(pillows\.su|pillowcase\.su)/f/([A-Za-z0-9_-]+)(?:$|[?#/])"#
    )
    nonisolated private static let imgurPattern = compile(
        #"^https?://(?:www\.)?((?:temp\.)?imgur\.gg)/f/([A-Za-z0-9_-]+)(?:$|[?#/])"#
    )
    nonisolated private static let frostePattern = compile(
        #"^https?://music\.froste\.lol/song/([a-f0-9]+)(?:$|[?#/])"#
    )
    nonisolated private static let krakenPattern = compile(
        #"^https?://(?:www\.)?krakenfiles\.com/view/[A-Za-z0-9_-]+/file\.html(?:$|[?#])"#
    )

    nonisolated static func isStreamableURL(_ url: String) -> Bool {
        let range = NSRange(url.startIndex..., in: url)
        return pillowsPattern.firstMatch(in: url, range: range) != nil
            || imgurPattern.firstMatch(in: url, range: range) != nil
            || frostePattern.firstMatch(in: url, range: range) != nil
            || krakenPattern.firstMatch(in: url, range: range) != nil
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
        let range = NSRange(originalLink.startIndex..., in: originalLink)

        if let m = pillowsPattern.firstMatch(in: originalLink, range: range),
           let idRange = Range(m.range(at: 2), in: originalLink) {
            return URL(string: "https://api.pillows.su/api/download/\(originalLink[idRange])")
        }

        if let m = frostePattern.firstMatch(in: originalLink, range: range),
           let hashRange = Range(m.range(at: 1), in: originalLink) {
            return URL(string: "https://music.froste.lol/song/\(originalLink[hashRange])/download")
        }

        if imgurPattern.firstMatch(in: originalLink, range: range) != nil {
            return URL(string: originalLink)
        }

        if krakenPattern.firstMatch(in: originalLink, range: range) != nil {
            return URL(string: originalLink)
        }

        return nil
    }
}
