#!/usr/bin/env swift
//
// Regenerates every app icon for iOS, macOS and tvOS from one geometric source.
// Run from the repo's LeakSheet-iOS directory:
//
//     xcrun swift Tools/make-icons.swift
//
// Idempotent: it rewrites the PNGs and the Contents.json files every time.
//
// The mark is a water droplet (a "leak") with a music note. The previous art
// was drawn by hand and had three defects this script fixes by construction:
//
//   1. The teardrop's straight flanks met its round body at a discontinuous
//      tangent, leaving a visible kink near the tip. Here the flanks run to the
//      TRUE tangent points of the circle, solved in closed form, so the join is
//      tangent-continuous by definition.
//   2. The specular highlight spilled outside the silhouette. Here it is
//      clipped to the droplet path.
//   3. The note was a separate fill whose colour differed per variant, so the
//      light and dark icons disagreed. Here it is an even-odd cut-out of the
//      same compound path, which is correct in every variant with no special
//      casing. (The tvOS layer stack draws it as a separate layer instead, in
//      the background colour, so it can parallax — visually identical when flat.)
//
// No third-party dependencies and no Python: the geometry is defined by
// tangency and even-odd path compositing, both of which are single CoreGraphics
// calls, and CoreGraphics is already on every machine that can build this app.

import CoreGraphics
import CoreText
import Foundation
import ImageIO
import UniformTypeIdentifiers

// MARK: - Palette

struct RGB {
    let r, g, b: CGFloat
    static func hex(_ v: UInt32) -> RGB {
        RGB(
            r: CGFloat((v >> 16) & 0xFF) / 255,
            g: CGFloat((v >> 8) & 0xFF) / 255,
            b: CGFloat(v & 0xFF) / 255
        )
    }
    var gray: RGB {
        let l = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return RGB(r: l, g: l, b: l)
    }
}

enum Variant {
    case light, dark, tinted

    /// Opaque background. App icons must never be transparent.
    var background: RGB {
        switch self {
        case .light: .hex(0xF2F7F7)
        case .dark: .hex(0x0B1414)
        case .tinted: .hex(0x000000)
        }
    }

    /// Droplet body gradient, top to bottom.
    var bodyTop: RGB {
        switch self {
        case .light, .dark: .hex(0x7FE3DC)
        case .tinted: RGB.hex(0x7FE3DC).gray
        }
    }

    var bodyBottom: RGB {
        switch self {
        case .light, .dark: .hex(0x2FB3AE)
        case .tinted: RGB.hex(0x2FB3AE).gray
        }
    }
}

// MARK: - Geometry (defined on a 1024×1024 reference canvas, y-up)

private enum G {
    static let canvas: CGFloat = 1024

    /// Circle forming the droplet's round body.
    static let center = CGPoint(x: 512, y: 404)
    static let radius: CGFloat = 300
    /// The tip. Its distance from the centre (512) must exceed the radius.
    static let apex = CGPoint(x: 512, y: 916)
}

/// The droplet: two straight flanks running from the apex to the circle's true
/// tangent points, then the major arc between them.
///
/// With `d = |apex − center|` and `γ = acos(R/d)`, the tangent points sit at
/// `β ∓ γ` where `β` is the direction from centre to apex. Because those are the
/// actual tangent points, each flank meets the arc with a continuous tangent —
/// this is the fix for the kink in the old art, and it is exact, not eyeballed.
func dropletPath() -> CGPath {
    let c = G.center, a = G.apex, r = G.radius
    let d = hypot(a.x - c.x, a.y - c.y)
    precondition(d > r, "apex must lie outside the circle")

    let beta = atan2(a.y - c.y, a.x - c.x)
    let gamma = acos(r / d)
    let right = beta - gamma
    let tangent = CGPoint(
        x: c.x + r * cos(right),
        y: c.y + r * sin(right)
    )

    let path = CGMutablePath()
    path.move(to: a)
    path.addLine(to: tangent)
    // Clockwise from the right tangent point sweeps the major arc, around the
    // bottom, to the left tangent point at `beta + gamma`.
    path.addArc(
        center: c,
        radius: r,
        startAngle: right,
        endAngle: beta + gamma,
        clockwise: true
    )
    path.closeSubpath()
    return path
}

/// The music note as SEPARATE head, stem and flag paths.
///
/// They must stay separate rather than being one compound path: the flag is
/// authored in the opposite winding direction to the CG-generated ellipse and
/// rounded rect, so a single non-zero fill cancels where the flag crosses the
/// stem and leaves a hairline. Filling each component on its own makes the
/// result their union regardless of winding.
func noteComponents() -> [CGPath] {
    // Head — an ellipse tilted the way a notehead is engraved.
    let head = CGMutablePath()
    head.addEllipse(
        in: CGRect(x: -104, y: -76, width: 208, height: 152),
        transform: CGAffineTransform(translationX: 432, y: 330)
            .rotated(by: -20 * .pi / 180)
    )

    let stem = CGMutablePath()
    stem.addRoundedRect(
        in: CGRect(x: 516, y: 330, width: 36, height: 368),
        cornerWidth: 18,
        cornerHeight: 18
    )

    // Flag — sweeps right and down off the stem's top, then returns along a
    // shallower curve so the shape stays a solid hook rather than a sliver.
    // Starts inside the stem so the two never share a coincident edge.
    let flag = CGMutablePath()
    flag.move(to: CGPoint(x: 518, y: 698))
    flag.addCurve(
        to: CGPoint(x: 686, y: 452),
        control1: CGPoint(x: 668, y: 662),
        control2: CGPoint(x: 712, y: 556)
    )
    flag.addCurve(
        to: CGPoint(x: 518, y: 566),
        control1: CGPoint(x: 664, y: 528),
        control2: CGPoint(x: 612, y: 556)
    )
    flag.closeSubpath()

    return [head, stem, flag]
}

// MARK: - Drawing

func makeContext(width: Int, height: Int) -> CGContext {
    guard let ctx = CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: CGColorSpace(name: CGColorSpace.sRGB)!,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        fatalError("could not create \(width)×\(height) context")
    }
    ctx.interpolationQuality = .high
    ctx.setAllowsAntialiasing(true)
    return ctx
}

func color(_ c: RGB, _ alpha: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: c.r, green: c.g, blue: c.b, alpha: alpha)
}

func fillGradient(_ ctx: CGContext, in rect: CGRect, from top: RGB, to bottom: RGB) {
    let gradient = CGGradient(
        colorsSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
        colors: [color(top), color(bottom)] as CFArray,
        locations: [0, 1]
    )!
    ctx.drawLinearGradient(
        gradient,
        start: CGPoint(x: rect.midX, y: rect.maxY),
        end: CGPoint(x: rect.midX, y: rect.minY),
        options: []
    )
}

/// Scales the 1024-reference geometry so it sits centred in `size`, occupying
/// `inset` of the smaller dimension.
func markTransform(size: CGSize, coverage: CGFloat = 1.0) -> CGAffineTransform {
    let s = min(size.width, size.height) / G.canvas * coverage
    return CGAffineTransform(translationX: (size.width - G.canvas * s) / 2,
                             y: (size.height - G.canvas * s) / 2)
        .scaledBy(x: s, y: s)
}

/// The droplet body, with the note cut out of it via even-odd, plus the
/// clipped highlight. `drawNoteAsHole == false` omits the note entirely (the
/// tvOS layer stack draws it on its own layer instead).
func drawMark(
    _ ctx: CGContext,
    size: CGSize,
    variant: Variant,
    transform: CGAffineTransform,
    drawNoteAsHole: Bool = true
) {
    let droplet = dropletPath().copy(using: [transform])!

    // Punched inside a transparency layer rather than filled even-odd against
    // the droplet: the note's own head, stem and flag OVERLAP each other, and
    // even-odd would fill those overlaps back in, leaving notches where the
    // stem meets the head and the flag. destinationOut removes the note's
    // non-zero-winding union, so the hole is exactly the note's silhouette.
    ctx.beginTransparencyLayer(auxiliaryInfo: nil)

    ctx.saveGState()
    ctx.addPath(droplet)
    ctx.clip()
    fillGradient(ctx, in: droplet.boundingBox, from: variant.bodyTop, to: variant.bodyBottom)
    ctx.restoreGState()

    if drawNoteAsHole {
        ctx.saveGState()
        ctx.setBlendMode(.destinationOut)
        ctx.setFillColor(CGColor(srgbRed: 0, green: 0, blue: 0, alpha: 1))
        for component in noteComponents() {
            ctx.addPath(component.copy(using: [transform])!)
            ctx.fillPath()
        }
        ctx.restoreGState()
    }

    ctx.endTransparencyLayer()

    drawHighlight(ctx, droplet: droplet, transform: transform)
}

/// Specular highlight, clipped to the silhouette so it can never spill outside
/// the droplet the way the old art's did.
func drawHighlight(_ ctx: CGContext, droplet: CGPath, transform: CGAffineTransform) {
    ctx.saveGState()
    ctx.addPath(droplet)
    ctx.clip()

    let highlight = CGMutablePath()
    let t = CGAffineTransform(translationX: 400, y: 640)
        .rotated(by: -25 * .pi / 180)
        .concatenating(transform)
    highlight.addEllipse(in: CGRect(x: -78, y: -118, width: 156, height: 236), transform: t)

    ctx.addPath(highlight)
    ctx.setFillColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 0.42))
    ctx.fillPath()
    ctx.restoreGState()
}

// MARK: - Whole-icon renderers

/// Full-bleed square icon: opaque background + mark. Used for iOS and as the
/// source for the macOS inset art.
func renderSquare(size: Int, variant: Variant) -> CGImage {
    let ctx = makeContext(width: size, height: size)
    let rect = CGRect(x: 0, y: 0, width: size, height: size)

    ctx.setFillColor(color(variant.background))
    ctx.fill(rect)

    drawMark(ctx, size: rect.size, variant: variant, transform: markTransform(size: rect.size))
    return ctx.makeImage()!
}

/// macOS icons are not full-bleed: the artwork is an 824-point rounded square
/// centred in a 1024 canvas, with the surrounding margin left for its shadow.
func renderMac(size: Int, variant: Variant) -> CGImage {
    let ctx = makeContext(width: size, height: size)
    let scale = CGFloat(size) / 1024
    let art = CGRect(x: 100 * scale, y: 100 * scale, width: 824 * scale, height: 824 * scale)
    let radius = 185.4 * scale

    // Shadow lives entirely inside the 100-point margin.
    ctx.saveGState()
    ctx.setShadow(
        offset: CGSize(width: 0, height: -10 * scale),
        blur: 20 * scale,
        color: CGColor(srgbRed: 0, green: 0, blue: 0, alpha: 0.25)
    )
    ctx.addPath(CGPath(roundedRect: art, cornerWidth: radius, cornerHeight: radius, transform: nil))
    ctx.setFillColor(color(variant.background))
    ctx.fillPath()
    ctx.restoreGState()

    ctx.saveGState()
    ctx.addPath(CGPath(roundedRect: art, cornerWidth: radius, cornerHeight: radius, transform: nil))
    ctx.clip()
    let inner = markTransform(size: art.size, coverage: 0.92)
        .concatenating(CGAffineTransform(translationX: art.minX, y: art.minY))
    drawMark(ctx, size: art.size, variant: variant, transform: inner)
    ctx.restoreGState()

    return ctx.makeImage()!
}

/// One layer of the tvOS parallax stack. Layers must be drawn separately —
/// slicing a flat render would not parallax.
enum TVLayer: String, CaseIterable {
    case back = "Back", middle = "Middle", front = "Front"
}

func renderTVLayer(_ layer: TVLayer, width: Int, height: Int, variant: Variant = .dark) -> CGImage {
    let ctx = makeContext(width: width, height: height)
    let rect = CGRect(x: 0, y: 0, width: width, height: height)
    // The mark is sized off the SHORT edge and centred, so a 400×240 icon and a
    // 1280×768 one show the same composition.
    let transform = markTransform(size: rect.size, coverage: 0.78)

    switch layer {
    case .back:
        // Opaque background layer with a soft vertical gradient.
        ctx.setFillColor(color(variant.background))
        ctx.fill(rect)
        ctx.saveGState()
        ctx.addRect(rect)
        ctx.clip()
        let g = CGGradient(
            colorsSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
            colors: [color(variant.bodyBottom, 0.30), color(variant.background, 0)] as CFArray,
            locations: [0, 1]
        )!
        ctx.drawRadialGradient(
            g,
            startCenter: CGPoint(x: rect.midX, y: rect.midY),
            startRadius: 0,
            endCenter: CGPoint(x: rect.midX, y: rect.midY),
            endRadius: rect.width * 0.6,
            options: []
        )
        ctx.restoreGState()

    case .middle:
        // Droplet body only — no note, so the note layer above can move over it.
        drawMark(ctx, size: rect.size, variant: variant, transform: transform, drawNoteAsHole: false)

    case .front:
        // Note, in the background colour, so flat it reads as a cut-out.
        ctx.setFillColor(color(variant.background))
        for component in noteComponents() {
            ctx.addPath(component.copy(using: [transform])!)
            ctx.fillPath()
        }
    }

    return ctx.makeImage()!
}

/// Top Shelf: a wide banner, not the square icon letterboxed. Droplet left of
/// centre with the wordmark beside it.
func renderTopShelf(width: Int, height: Int) -> CGImage {
    let variant = Variant.dark
    let ctx = makeContext(width: width, height: height)
    let rect = CGRect(x: 0, y: 0, width: width, height: height)

    ctx.setFillColor(color(variant.background))
    ctx.fill(rect)
    ctx.saveGState()
    ctx.addRect(rect)
    ctx.clip()
    let g = CGGradient(
        colorsSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
        colors: [color(variant.bodyBottom, 0.28), color(variant.background, 0)] as CFArray,
        locations: [0, 1]
    )!
    ctx.drawRadialGradient(
        g,
        startCenter: CGPoint(x: rect.width * 0.28, y: rect.midY),
        startRadius: 0,
        endCenter: CGPoint(x: rect.width * 0.28, y: rect.midY),
        endRadius: rect.width * 0.45,
        options: []
    )
    ctx.restoreGState()

    let markSide = CGFloat(height) * 0.72
    let markRect = CGRect(
        x: rect.width * 0.22 - markSide / 2,
        y: (rect.height - markSide) / 2,
        width: markSide,
        height: markSide
    )
    let transform = markTransform(size: markRect.size)
        .concatenating(CGAffineTransform(translationX: markRect.minX, y: markRect.minY))
    drawMark(ctx, size: markRect.size, variant: variant, transform: transform)

    // Wordmark.
    let fontSize = CGFloat(height) * 0.17
    // CoreText's own attribute keys — the `.font` / `.foregroundColor`
    // NSAttributedString.Key constants ship with AppKit/UIKit, not Foundation.
    let font = CTFontCreateWithName("SFProDisplay-Semibold" as CFString, fontSize, nil)
    let attrs: CFDictionary = [
        kCTFontAttributeName as String: font,
        kCTForegroundColorAttributeName as String: CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 0.95),
    ] as CFDictionary
    let line = CTLineCreateWithAttributedString(
        CFAttributedStringCreate(nil, "LeakSheet" as CFString, attrs)!
    )
    let bounds = CTLineGetBoundsWithOptions(line, .useOpticalBounds)
    ctx.textPosition = CGPoint(
        x: markRect.maxX + CGFloat(height) * 0.10,
        y: rect.midY - bounds.height / 2 - bounds.minY
    )
    CTLineDraw(line, ctx)

    return ctx.makeImage()!
}

// MARK: - Output

func write(_ image: CGImage, to path: String) {
    let url = URL(fileURLWithPath: path)
    try! FileManager.default.createDirectory(
        at: url.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    guard let dest = CGImageDestinationCreateWithURL(
        url as CFURL, UTType.png.identifier as CFString, 1, nil
    ) else {
        fatalError("could not open \(path) for writing")
    }
    CGImageDestinationAddImage(dest, image, nil)
    guard CGImageDestinationFinalize(dest) else { fatalError("could not write \(path)") }
    print("  \(image.width)×\(image.height)  \(path)")
}

func writeJSON(_ object: Any, to path: String) {
    let url = URL(fileURLWithPath: path)
    try! FileManager.default.createDirectory(
        at: url.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    let data = try! JSONSerialization.data(
        withJSONObject: object,
        options: [.prettyPrinted, .sortedKeys]
    )
    try! data.write(to: url)
}

let info: [String: Any] = ["author": "xcode", "version": 1]

// MARK: - iOS + macOS asset catalog

let appIconSet = "LeakSheet/Assets.xcassets/AppIcon.appiconset"
print("iOS + macOS → \(appIconSet)")

// Clear the old hand-drawn PNGs so a stale file can't survive a rename.
for stale in (try? FileManager.default.contentsOfDirectory(atPath: appIconSet)) ?? [] where stale.hasSuffix(".png") {
    try? FileManager.default.removeItem(atPath: "\(appIconSet)/\(stale)")
}

var appIconImages: [[String: Any]] = []

// The old catalog had this backwards: the file named "light" carried the DARK
// background and was the default entry, and the "dark" one was white.
for (variant, name, appearances) in [
    (Variant.light, "AppIcon-light", [] as [[String: String]]),
    (.dark, "AppIcon-dark", [["appearance": "luminosity", "value": "dark"]]),
    (.tinted, "AppIcon-tinted", [["appearance": "luminosity", "value": "tinted"]]),
] {
    write(renderSquare(size: 1024, variant: variant), to: "\(appIconSet)/\(name).png")
    // No "scale" key: its absence is what marks this as the modern single-size
    // iOS app icon. With it, actool treats the entry as a legacy sized slot and
    // warns that the 1024, 60@2x, 76@2x and 83.5@2x icons are all missing.
    var entry: [String: Any] = [
        "filename": "\(name).png",
        "idiom": "universal",
        "platform": "ios",
        "size": "1024x1024",
    ]
    if !appearances.isEmpty { entry["appearances"] = appearances }
    appIconImages.append(entry)
}

for (points, scales) in [(16, [1, 2]), (32, [1, 2]), (128, [1, 2]), (256, [1, 2]), (512, [1, 2])] {
    for scale in scales {
        let px = points * scale
        let name = "AppIcon-mac-\(points)x\(points)@\(scale)x.png"
        write(renderMac(size: px, variant: .light), to: "\(appIconSet)/\(name)")
        appIconImages.append([
            "filename": name,
            "idiom": "mac",
            "scale": "\(scale)x",
            "size": "\(points)x\(points)",
        ])
    }
}

writeJSON(["images": appIconImages, "info": info], to: "\(appIconSet)/Contents.json")

// MARK: - tvOS brand assets

let brand = "LeakSheetTV/Assets.xcassets/App Icon & Top Shelf Image.brandassets"
print("tvOS → \(brand)")

/// One `.imagestack` with its three `.imagestacklayer`s.
func writeImageStack(named name: String, at base: String, width: Int, height: Int) {
    let stack = "\(base)/\(name).imagestack"
    var layerRefs: [[String: String]] = []

    for layer in TVLayer.allCases {
        let dir = "\(stack)/\(layer.rawValue).imagestacklayer"
        let imageset = "\(dir)/Content.imageset"
        var images: [[String: Any]] = []
        for scale in [1, 2] {
            let file = "\(layer.rawValue)@\(scale)x.png"
            write(
                renderTVLayer(layer, width: width * scale, height: height * scale),
                to: "\(imageset)/\(file)"
            )
            images.append(["filename": file, "idiom": "tv", "scale": "\(scale)x"])
        }
        writeJSON(["images": images, "info": info], to: "\(imageset)/Contents.json")
        writeJSON(["info": info], to: "\(dir)/Contents.json")
        layerRefs.append(["filename": "\(layer.rawValue).imagestacklayer"])
    }

    // `layers` is ordered FRONT to BACK. actool requires the last entry — the
    // backmost layer — to be a fully opaque bitmap, so this must be reversed
    // from the natural back-to-front drawing order.
    // Array(...) matters: JSONSerialization cannot serialize a ReversedCollection.
    writeJSON(["info": info, "layers": Array(layerRefs.reversed())], to: "\(stack)/Contents.json")
}

writeImageStack(named: "App Icon", at: brand, width: 400, height: 240)
writeImageStack(named: "App Icon - App Store", at: brand, width: 1280, height: 768)

func writeTopShelf(named name: String, at base: String, width: Int, height: Int) {
    let imageset = "\(base)/\(name).imageset"
    var images: [[String: Any]] = []
    for scale in [1, 2] {
        let file = "\(name.replacingOccurrences(of: " ", with: "-"))@\(scale)x.png"
        write(renderTopShelf(width: width * scale, height: height * scale), to: "\(imageset)/\(file)")
        images.append(["filename": file, "idiom": "tv", "scale": "\(scale)x"])
    }
    writeJSON(["images": images, "info": info], to: "\(imageset)/Contents.json")
}

writeTopShelf(named: "Top Shelf Image", at: brand, width: 1920, height: 720)
writeTopShelf(named: "Top Shelf Image Wide", at: brand, width: 2320, height: 720)

writeJSON([
    "assets": [
        ["filename": "App Icon.imagestack", "idiom": "tv", "role": "primary-app-icon", "size": "400x240"],
        ["filename": "App Icon - App Store.imagestack", "idiom": "tv", "role": "primary-app-icon", "size": "1280x768"],
        ["filename": "Top Shelf Image.imageset", "idiom": "tv", "role": "top-shelf-image", "size": "1920x720"],
        ["filename": "Top Shelf Image Wide.imageset", "idiom": "tv", "role": "top-shelf-image-wide", "size": "2320x720"],
    ],
    "info": info,
], to: "\(brand)/Contents.json")

// tvOS needs its own accent colour; it does not share the iOS catalog.
writeJSON([
    "colors": [[
        "color": [
            "color-space": "srgb",
            "components": ["alpha": "1.000", "blue": "0xF5", "green": "0x94", "red": "0x58"],
        ],
        "idiom": "universal",
    ]],
    "info": info,
], to: "LeakSheetTV/Assets.xcassets/AccentColor.colorset/Contents.json")
writeJSON(["info": info], to: "LeakSheetTV/Assets.xcassets/Contents.json")

print("done")
