import Foundation
#if os(iOS)
import BackgroundTasks
#endif

/// Maps a tracker-load phase to 0...100 and the line the system progress UI shows.
nonisolated enum LoadProgress {
    static func of(_ phase: APIClient.LoadPhase) -> (units: Int64, subtitle: String) {
        switch phase {
        case .readingCache:
            return (5, "Reading saved copy")
        case .connecting:
            return (10, "Connecting")
        case .server(let message, let done, let total):
            guard let done, let total, total > 0 else { return (30, message) }
            return (Int64(10 + 50 * min(done, total) / total), message)
        case .downloading(let received, let expected):
            guard let expected, expected > 0 else { return (70, "Downloading") }
            return (60 + 30 * min(received, expected) / expected, "Downloading")
        case .preparing:
            return (95, "Preparing")
        }
    }
}

#if os(iOS)
/// Keeps a slow tracker load running after the user leaves the app, with the system's own
/// progress Live Activity. Loads under `delay` (cache replays, warm hits) never show one.
@MainActor
final class LoadActivity {
    static let shared = LoadActivity()

    private static let identifier = "si.safko.LeakSheet.load"
    private static let delay: Duration = .seconds(2)

    private struct TaskBox: @unchecked Sendable { let task: BGContinuedProcessingTask }

    private var registered = false
    private var generation = 0
    private var active = false
    private var task: BGContinuedProcessingTask?
    private var title = ""
    private var latest: (units: Int64, subtitle: String) = (0, "Starting")

    func begin(name: String) {
        generation += 1
        active = true
        title = "Loading \(name)"
        latest = (0, "Starting")
        let mine = generation
        Task {
            try? await Task.sleep(for: Self.delay)
            if active && generation == mine { submit() }
        }
    }

    func report(_ phase: APIClient.LoadPhase?) {
        guard active, let phase else { return }
        latest = LoadProgress.of(phase)
        push()
    }

    func end(success: Bool) {
        active = false
        guard let task else {
            // Not launched yet (or never submitted): drop the pending request.
            BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: Self.identifier)
            return
        }
        task.progress.completedUnitCount = task.progress.totalUnitCount
        task.setTaskCompleted(success: success)
        self.task = nil
    }

    private func submit() {
        if !registered {
            registered = true
            BGTaskScheduler.shared.register(forTaskWithIdentifier: Self.identifier, using: nil) { task in
                guard let task = task as? BGContinuedProcessingTask else { return }
                let box = TaskBox(task: task)
                Task { @MainActor in LoadActivity.shared.attach(box.task) }
            }
        }
        let request = BGContinuedProcessingTaskRequest(identifier: Self.identifier, title: title, subtitle: latest.subtitle)
        // A stale queued load is worse than none: fail instead of waiting for room.
        request.strategy = .fail
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            // A refused request means a backgrounded load just stops: worth knowing about.
            Telemetry.report("Load activity submit failed: \(error)", category: "LoadActivity")
        }
    }

    private func attach(_ task: BGContinuedProcessingTask) {
        // The load finished while the system was launching the task.
        guard active else { task.setTaskCompleted(success: true); return }
        self.task = task
        task.progress.totalUnitCount = 100
        let box = TaskBox(task: task)
        task.expirationHandler = { [weak self] in
            Task { @MainActor in self?.expire(box.task) }
        }
        push()
    }

    /// The user cancelled in the system UI or the system reclaimed the task; the load itself carries on.
    private func expire(_ expired: BGContinuedProcessingTask) {
        guard task === expired else { return }
        task = nil
        expired.setTaskCompleted(success: false)
    }

    private func push() {
        guard let task else { return }
        task.progress.completedUnitCount = latest.units
        task.updateTitle(title, subtitle: latest.subtitle)
    }
}
#else
@MainActor
final class LoadActivity {
    static let shared = LoadActivity()
    func begin(name: String) {}
    func report(_ phase: APIClient.LoadPhase?) {}
    func end(success: Bool) {}
}
#endif
