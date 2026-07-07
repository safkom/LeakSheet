import Testing

@testable import LeakSheet

struct PlayerViewModelTests {
    @Test func `formatTime renders minutes and zero-padded seconds`() {
        #expect(PlayerViewModel.formatTime(0) == "0:00")
        #expect(PlayerViewModel.formatTime(59) == "0:59")
        #expect(PlayerViewModel.formatTime(60) == "1:00")
        #expect(PlayerViewModel.formatTime(61.4) == "1:01")
        #expect(PlayerViewModel.formatTime(3599) == "59:59")
    }

    @Test func `formatTime guards non-finite and negative input`() {
        #expect(PlayerViewModel.formatTime(-5) == "0:00")
        #expect(PlayerViewModel.formatTime(.infinity) == "0:00")
        #expect(PlayerViewModel.formatTime(.nan) == "0:00")
    }
}
