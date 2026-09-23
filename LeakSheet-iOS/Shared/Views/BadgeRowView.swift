import SwiftUI

/// Quality + availability badges for a song version, deduped per SPEC §12.
struct BadgeRowView: View {
    let version: SongVersion
    var trailing: String? = nil

    var body: some View {
        DedupedBadgePills(quality: version.quality, availability: version.availableLength, trailing: trailing)
    }
}
