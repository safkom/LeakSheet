import SwiftUI

/// The appearance the user picked in Settings.
///
/// iOS defaults to Dark, the look the app was drawn for; the choice exists so
/// the light palette — tuned and contrast-tested, but previously reachable
/// only on the Mac — is available to anyone who wants it. The Mac defaults to
/// System, which is what it already did. See DECISIONS.md::AppAppearance.swift.
enum AppAppearance: String, CaseIterable, Identifiable {
    case dark
    case light
    case system

    static let storageKey = "leaksheet_appearance"

    static var platformDefault: AppAppearance {
        #if os(macOS)
        .system
        #else
        .dark
        #endif
    }

    var id: Self { self }

    var label: String {
        switch self {
        case .dark: "Dark"
        case .light: "Light"
        case .system: "System"
        }
    }

    /// Nil follows the system. That only works because the iOS target no
    /// longer forces `UIUserInterfaceStyle = Dark` in its Info.plist, which
    /// would override this.
    var colorScheme: ColorScheme? {
        switch self {
        case .dark: .dark
        case .light: .light
        case .system: nil
        }
    }
}
