import Foundation
import OSLog
import Sentry

/// Crash, error and log reporting to the self-hosted GlitchTip (Sentry protocol).
nonisolated enum Telemetry {
    /// The leaksheet-ios project's DSN. Public by design: it can only submit events.
    private static let dsn = "https://c19622c356c34b4b9fcdef0b0d22f9d8@glitchtip.safko.eu/2"

    static func start() {
        // A test host launching the app must not report.
        guard ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] == nil else { return }
        SentrySDK.start { options in
            options.dsn = dsn
            options.enableLogs = true
            options.enableAutoSessionTracking = false  // GlitchTip has no sessions
            options.tracesSampleRate = 0
            options.sendDefaultPii = false
            // 502 is an upstream host being down (pillows) or an expired cover token:
            // logged where it matters, not an issue of ours.
            options.failedRequestStatusCodes = [
                HttpStatusCodeRange(min: 500, max: 501), HttpStatusCodeRange(min: 503, max: 599),
            ]
            #if DEBUG
            options.environment = "debug"
            #endif
        }
    }

    /// Logs locally and records the failure in GlitchTip.
    static func report(_ message: String, category: String, attributes: [String: Any] = [:]) {
        Logger(subsystem: "si.safko.LeakSheet", category: category).error("\(message, privacy: .public)")
        SentrySDK.logger.error(message, attributes: attributes.merging(["category": category]) { a, _ in a })
    }
}
