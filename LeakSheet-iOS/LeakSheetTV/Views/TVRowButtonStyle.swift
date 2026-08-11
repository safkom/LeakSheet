import SwiftUI

/// Row-shaped focus style. `.card` is right for tiles but far too heavy for a
/// dense list row, and tvOS has no hover state to fall back on — focus is the
/// only affordance, so it has to be unmistakable.
struct TVRowButtonStyle: ButtonStyle {
    @Environment(\.isFocused) private var isFocused

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background {
                RoundedRectangle(cornerRadius: 12)
                    .fill(isFocused ? Color.white.opacity(0.16) : .clear)
            }
            .overlay {
                RoundedRectangle(cornerRadius: 12)
                    .stroke(isFocused ? Color.white.opacity(0.35) : .clear, lineWidth: 2)
            }
            .scaleEffect(isFocused ? 1.02 : 1)
            .animation(.easeOut(duration: 0.15), value: isFocused)
    }
}
