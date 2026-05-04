import SwiftUI

/// Side navigation rail showing era abbreviations.
struct EraNavView: View {
    let eras: [Era]
    let expandedEra: String?
    var onTap: (String) -> Void

    var body: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(spacing: 2) {
                ForEach(eras, id: \.name) { era in
                    Button {
                        Haptics.light()
                        onTap(era.name)
                    } label: {
                        Text(abbreviation(era.name))
                            .font(.system(size: 11, weight: .medium, design: .rounded))
                            .foregroundStyle(expandedEra == era.name ? .white : .secondary)
                            .frame(width: 28, height: 24)
                            .contentShape(Rectangle())
                            .frame(minHeight: 44)
                    }
                    .buttonStyle(.glass)
                }
            }
            .padding(.vertical, 4)
        }
        .frame(width: 32)
        .glassEffect(in: .rect(cornerRadius: 8))
        .padding(.trailing, 4)
        .padding(.vertical, 60)
    }

    private func abbreviation(_ name: String) -> String {
        let words = name.split(separator: " ")
        if words.count <= 2 {
            return String(name.prefix(3)).uppercased()
        }
        return words.prefix(3)
            .compactMap { $0.first.map { String($0).uppercased() } }
            .joined()
    }
}
