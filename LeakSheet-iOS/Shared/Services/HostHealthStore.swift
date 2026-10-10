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
        guard let hosts = try? await APIClient.shared.fetchHostHealth() else { return }
        downHosts = Self.downHosts(from: hosts)
        lastRefresh = Date()
    }

    nonisolated static func downHosts(from hosts: [HostStatus]) -> [String: String] {
        Dictionary(hosts.filter(\.isDown).map { ($0.provider, $0.host) }, uniquingKeysWith: { first, _ in first })
    }
}
