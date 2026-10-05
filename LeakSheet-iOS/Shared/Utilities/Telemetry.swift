import Foundation
import OSLog
import Sentry

/// Crash, error and log reporting to the self-hosted GlitchTip (Sentry protocol).
nonisolated enum Telemetry {
    /// The leaksheet-ios project's DSN. Public by design: it can only submit events.
    private static let dsn = "https://c19622c356c34b4b9fcdef0b0d22f9d8@glitchtip.safko.eu/2"

    static func start() {
        // Debug builds and test hosts must not report: they are not what users run.
        #if DEBUG
        return
        #else
        SentrySDK.start { options in
            options.dsn = dsn
            options.enableLogs = true
            options.enableAutoSessionTracking = false  // GlitchTip has no sessions
            options.tracesSampleRate = 0
            options.sendDefaultPii = false
            // The API's own 5xx are upstream outages it already logs; Cloudflare's 52x (origin
            // timeouts and connection errors) are visible from here alone.
            options.failedRequestStatusCodes = [HttpStatusCodeRange(min: 520, max: 599)]
        }
        #endif
    }

    /// Logs locally and records the failure in GlitchTip.
    static func report(_ message: String, category: String, attributes: [String: Any] = [:]) {
        Logger(subsystem: "si.safko.LeakSheet", category: category).error("\(message, privacy: .public)")
        SentrySDK.logger.error(message, attributes: attributes.merging(["category": category]) { a, _ in a })
    }
}
