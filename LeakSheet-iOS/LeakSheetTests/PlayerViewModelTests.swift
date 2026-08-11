import Testing

@testable import LeakSheet

struct PlayerViewModelTests {
    @Test func `formatTime renders minutes and zero-padded seconds`() {
        #expect(Format.time(0) == "0:00")
        #expect(Format.time(59) == "0:59")
        #expect(Format.time(60) == "1:00")
        #expect(Format.time(61.4) == "1:01")
        #expect(Format.time(3599) == "59:59")
    }

    @Test func `formatTime guards non-finite and negative input`() {
        #expect(Format.time(-5) == "0:00")
        #expect(Format.time(.infinity) == "0:00")
        #expect(Format.time(.nan) == "0:00")
    }
}
