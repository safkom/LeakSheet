import Foundation

/// Content kind for one Misc/Music-Video entry link. The sheet's Link(s)
/// column mixes audio streams, direct images, videos, and zip/archive
/// downloads with no structured type field — the URL itself (host, path
/// extension) is the only reliable signal, so this drives which affordance
/// a row shows for each link.
nonisolated enum MiscLinkKind: Sendable, Equatable {
    case stream   // playable via the existing StreamResolver hosts
    case image    // direct image file or a known image-hosting host
    case video    // a direct video file
    case embed    // YouTube/Vimeo/SoundCloud — official in-app embed player
    case archive  // zip/rar/7z or a known file-locker host
    case link     // anything else — in-app Safari

    var systemImage: String {
        switch self {
        case .stream: return "play.circle"
        case .image: return "photo"
        case .video: return "film"
        case .embed: return "play.rectangle"
        case .archive: return "archivebox"
        case .link: return "arrow.up.right.square"
        }
    }
}

/// One classified link on a Misc entry, with a short host-derived label so
/// multiple links on the same entry are distinguishable at a glance (e.g.
/// "pillows.su" vs "YouTube" vs "Archive").
nonisolated struct MiscLink: Identifiable, Sendable, Equatable {
    let url: String
    let kind: MiscLinkKind
    let label: String

    var id: String { url }
}

nonisolated enum MiscLinkClassifier {
    private static let imageExtensions: Set<String> = ["jpg", "jpeg", "png", "gif", "webp", "bmp", "heic"]
    private static let archiveExtensions: Set<String> = ["zip", "rar", "7z", "tar", "gz"]
    private static let videoExtensions: Set<String> = ["mp4", "mov", "m4v", "webm", "mkv", "avi"]

    /// Hosts whose content plays through their official embed widget.
    private static let embedHosts: Set<String> = [
        "youtube.com", "m.youtube.com", "youtu.be", "vimeo.com",
        "soundcloud.com", "m.soundcloud.com", "on.soundcloud.com",
    ]
    /// drive.google.com stays here as a fallback for folder and uc?id=
    /// links; single-file /file/d/ links classify as .stream first via
    /// StreamResolver.
    private static let archiveHosts: Set<String> = [
        "mega.nz", "mediafire.com", "drive.google.com",
    ]
    private static let imageHosts: Set<String> = [
        "i.imgur.com", "ibb.co", "i.ibb.co", "postimg.cc", "i.postimg.cc",
    ]

    /// Classifies a raw link URL. A video file extension wins over the
    /// streamable-host shortcut below — a .mp4/.mov/.m4v/.webm/.mkv/.avi
    /// file hosted on e.g. pillows.su is still a video, not an audio stream,
    /// and must not be silently routed into the audio-only player. Only
    /// after that check do we fall back to the streamable-host list —
    /// pillows.su/imgur.gg/froste.lol/krakenfiles links with no video
    /// extension always play through the app's audio player regardless of
    /// what they actually host.
    static func classify(_ urlString: String) -> MiscLinkKind {
        guard let url = URL(string: urlString), let host = normalizedHost(url) else { return .link }
        let ext = url.pathExtension.lowercased()

        if videoExtensions.contains(ext) { return .video }
        if StreamResolver.isStreamableURL(urlString) { return .stream }
        if archiveExtensions.contains(ext) || archiveHosts.contains(host) { return .archive }
        if embedHosts.contains(host) { return .embed }
        if imageExtensions.contains(ext) || imageHosts.contains(host) { return .image }
        return .link
    }

    /// Short, human-friendly label derived from the host — falls back to the
    /// bare host for anything not specifically named.
    static func label(for urlString: String, kind: MiscLinkKind) -> String {
        guard let url = URL(string: urlString), let host = normalizedHost(url) else { return "Link" }
        switch host {
        case "youtube.com", "m.youtube.com", "youtu.be": return "YouTube"
        case "vimeo.com": return "Vimeo"
        case "soundcloud.com", "m.soundcloud.com", "on.soundcloud.com": return "SoundCloud"
        case "drive.google.com": return "Google Drive"
        case "mega.nz": return "Mega"
        case "mediafire.com": return "MediaFire"
        case "archive.org", "web.archive.org": return "Archive"
        case "instagram.com": return "Instagram"
        case "twitter.com", "x.com": return "Twitter/X"
        default: return host
        }
    }

    /// Best-effort preview image URL for a link, derivable without fetching
    /// the linked page — a direct image file is its own thumbnail, and
    /// YouTube's thumbnail path is predictable from the video id. Nil for
    /// everything else (streams, archives, generic links, Vimeo).
    static func thumbnailURL(for urlString: String, kind: MiscLinkKind) -> String? {
        switch kind {
        case .image:
            return urlString
        case .embed:
            guard let id = youTubeVideoID(from: urlString) else { return nil }
            return "https://img.youtube.com/vi/\(id)/hqdefault.jpg"
        case .stream, .video, .archive, .link:
            return nil
        }
    }

    /// Official embed-player URL for an embeddable link — the ToS-safe way
    /// to play YouTube/Vimeo/SoundCloud in-app. Nil for everything else
    /// (the caller falls back to the in-app Safari sheet).
    static func embedURL(for urlString: String) -> URL? {
        guard let url = URL(string: urlString), let host = normalizedHost(url) else { return nil }
        if let id = youTubeVideoID(from: urlString) {
            return URL(string: "https://www.youtube.com/embed/\(id)?playsinline=1")
        }
        if host == "vimeo.com" {
            if let id = URLComponents(string: urlString)?.path.split(separator: "/").first,
               id.allSatisfy(\.isNumber) {
                return URL(string: "https://player.vimeo.com/video/\(id)")
            }
            return nil
        }
        if host == "soundcloud.com" || host == "m.soundcloud.com" || host == "on.soundcloud.com" {
            guard let encoded = urlString.addingPercentEncoding(withAllowedCharacters: .alphanumerics) else { return nil }
            return URL(string: "https://w.soundcloud.com/player/?url=\(encoded)&auto_play=false")
        }
        return nil
    }

    private static func normalizedHost(_ url: URL) -> String? {
        guard var host = url.host?.lowercased() else { return nil }
        if host.hasPrefix("www.") { host.removeFirst(4) }
        return host
    }

    private static func youTubeVideoID(from urlString: String) -> String? {
        guard let components = URLComponents(string: urlString),
              let host = normalizedHost(URL(string: urlString) ?? URL(fileURLWithPath: "/"))
        else { return nil }
        if host == "youtu.be" {
            return components.path.split(separator: "/").first.map(String.init)
        }
        if host == "youtube.com" || host == "m.youtube.com" {
            if let v = components.queryItems?.first(where: { $0.name == "v" })?.value { return v }
            let parts = components.path.split(separator: "/")
            if parts.count >= 2, ["embed", "shorts"].contains(parts[0]) {
                return String(parts[1])
            }
        }
        return nil
    }
}
