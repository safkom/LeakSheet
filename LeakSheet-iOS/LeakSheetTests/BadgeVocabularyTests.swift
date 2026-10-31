import Testing

@testable import LeakSheet

/// Spellings the 471-tracker sweep found that used to fall to Unknown.
struct BadgeVocabularyTests {
    @Test func `short and format quality spellings map to their tier`() {
        #expect(qualityVariant("HQ") == .highQuality)
        #expect(qualityVariant("LQ") == .lowQuality)
        #expect(qualityVariant("FLAC") == .lossless)
        #expect(qualityVariant("WAV") == .lossless)
        #expect(qualityVariant("High Quality\n(320kbps)") == .highQuality)
        #expect(qualityVariant("Низкое Качество") == .lowQuality)
        #expect(qualityVariant("Высокое Качество") == .highQuality)
    }

    @Test func `short tokens match whole words only`() {
        // "HQ" inside a word is not the quality tier.
        #expect(qualityVariant("Not Available") == .notAvailable)
        #expect(qualityVariant("Performance") == .notAvailable)
    }

    @Test func `availability spellings`() {
        #expect(availabilityVariant("Original File") == .ogfile)
        #expect(availabilityVariant("Lost") == .unavailable)
        #expect(availabilityVariant("Lost Media") == .unavailable)
        // Unchanged neighbours.
        #expect(availabilityVariant("OG File") == .ogfile)
        #expect(availabilityVariant("Full") == .full)
    }
}
