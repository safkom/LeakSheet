import SwiftUI

/// The appearance the user picked in Settings: iOS defaults to Dark, the Mac to
/// System. See DECISIONS.md::AppAppearance.swift.
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

    /// Nil follows the system, which works only because the iOS Info.plist does not
    /// force `UIUserInterfaceStyle`.
    var colorScheme: ColorScheme? {
        switch self {
        case .dark: .dark
        case .light: .light
        case .system: nil
        }
    }
}
