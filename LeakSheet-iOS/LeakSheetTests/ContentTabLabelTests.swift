import Testing

@testable import LeakSheet

/// The tab bar draws an SF Symbol per tab, so a tab name's leading emoji is dropped.
struct ContentTabLabelTests {
    @Test func `leading emoji is dropped`() {
        #expect(ContentTabsView.labelText(for: "📁 Misc") == "Misc")
        #expect(ContentTabsView.labelText(for: "📁Misc") == "Misc")
        #expect(ContentTabsView.labelText(for: "🎥 Music Videos") == "Music Videos")
    }

    @Test func `names without emoji are unchanged`() {
        #expect(ContentTabsView.labelText(for: "Misc") == "Misc")
        #expect(ContentTabsView.labelText(for: "Music Videos") == "Music Videos")
    }

    @Test func `leading digits are kept`() {
        #expect(ContentTabsView.labelText(for: "2024 Leaks") == "2024 Leaks")
    }

    @Test func `inner and trailing emoji are kept`() {
        #expect(ContentTabsView.labelText(for: "Misc 🎥") == "Misc 🎥")
    }

    @Test func `emoji-only name falls back to the original`() {
        #expect(ContentTabsView.labelText(for: "🎥") == "🎥")
    }
}
