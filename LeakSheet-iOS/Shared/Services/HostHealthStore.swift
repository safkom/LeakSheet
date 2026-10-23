import Foundation
import Observation

/// Which streaming providers the backend reports as down (`GET /hosts`), so a row can
/// show it before a tap and the player can say why a play failed.
/// See DECISIONS.md::HostHealthStore.swift.
@Observable
final class HostHealthStore {
    static let shared = HostHealthStore()

    /// Provider key -> display host ("pillows" -> "pillows.su") for providers that are down.
    private(set) var downHosts: [String: String] = [:]

    @ObservationIgnored private var lastRefresh: Date?
    @ObservationIgnored private var refreshing = false
    @ObservationIgnored private var generation = 0
    private static let minimumInterval: TimeInterval = 60

    func isDown(link: String?) -> Bool {
        downHost(for: link) != nil
    }

    /// The host a link streams from, when the backend reports it down.
    func downHost(for link: String?) -> String? {
        guard let link, let provider = StreamResolver.provider(for: link) else { return nil }
        return downHosts[provider]
    }

    /// Re-read `/hosts`, at most once a minute unless `force`. A failed fetch keeps the
    /// last known state: it says nothing about the providers.
    func refresh(force: Bool = false) async {
        guard !refreshing else { return }
        if !force, let lastRefresh, Date().timeIntervalSince(lastRefresh) < Self.minimumInterval { return }
        refreshing = true
        defer { refreshing = false }
        let started = generation
        guard let hosts = try? await APIClient.shared.fetchHostHealth() else { return }
        // An answer from before a reset describes the old server.
        guard started == generation else { return }
        downHosts = Self.downHosts(from: hosts)
        lastRefresh = Date()
    }

    /// Drops the last answer, so a backend change doesn't inherit the old one's down hosts.
    /// A refresh already in flight is discarded when it returns; clearing `refreshing` lets the next one run.
    func reset() {
        generation += 1
        refreshing = false
        downHosts = [:]
        lastRefresh = nil
    }

    nonisolated static func downHosts(from hosts: [HostStatus]) -> [String: String] {
        Dictionary(hosts.filter(\.isDown).map { ($0.provider, $0.host) }, uniquingKeysWith: { first, _ in first })
    }
}
