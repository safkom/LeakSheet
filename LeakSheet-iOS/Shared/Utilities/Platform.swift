import SwiftUI

#if canImport(AppKit)
import AppKit
#elseif canImport(UIKit)
import UIKit
#endif

/// The whole cross-platform shim surface. Everything else in the app is either
/// already portable or forks inside a file that was platform-specific anyway.
/// See DECISIONS.md::Platform.swift::shim-surface.

// MARK: - Clipboard

/// Clipboard access. tvOS has no pasteboard at all, so it degrades to a no-op;
/// the tvOS URL screen omits its Paste button outright rather than showing a
/// control that does nothing.
enum Pasteboard {
    static var string: String? {
        #if canImport(AppKit)
        NSPasteboard.general.string(forType: .string)
        #elseif os(iOS)
        UIPasteboard.general.string
        #else
        nil
        #endif
    }

    static func copy(_ value: String) {
        #if canImport(AppKit)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
        #elseif os(iOS)
        UIPasteboard.general.string = value
        #endif
    }
}

// MARK: - Platform image

/// Wraps a `CGImage` in the platform's image class. The app's image pipeline is
/// `CGImage` end to end; this exists solely for `MPMediaItemArtwork`, whose
/// request handler is `TARGET_OS_IPHONE`-forked in the MediaPlayer headers.
/// `nonisolated` because the artwork handler runs on an arbitrary thread.
nonisolated func platformImage(_ cgImage: CGImage) -> PlatformImage {
    #if canImport(AppKit)
    NSImage(cgImage: cgImage, size: NSSize(width: cgImage.width, height: cgImage.height))
    #else
    UIImage(cgImage: cgImage)
    #endif
}

#if canImport(AppKit)
typealias PlatformImage = NSImage
#else
typealias PlatformImage = UIImage
#endif

// MARK: - View modifiers

extension View {
    /// URL-entry keyboard traits. macOS has no software keyboard, so these
    /// modifiers don't exist there.
    func urlFieldTraits() -> some View {
        #if os(macOS)
        self
        #else
        self
            .keyboardType(.URL)
            .textInputAutocapitalization(.never)
            .textContentType(.URL)
        #endif
    }

    /// Pointer hover highlight. Only macOS has a persistent cursor.
    ///
    /// A no-op elsewhere, and not a modifier there at all: the modifier's
    /// `@State` sat outside the platform check, so every row on iOS and tvOS
    /// allocated hover storage nothing ever read.
    @ViewBuilder
    func rowHoverHighlight() -> some View {
        #if os(macOS)
        modifier(RowHoverHighlight())
        #else
        self
        #endif
    }
}

#if os(macOS)
private struct RowHoverHighlight: ViewModifier {
    @State private var hovering = false

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.white.opacity(hovering ? 0.05 : 0))
            )
            .onHover { hovering = $0 }
    }
}
#endif
