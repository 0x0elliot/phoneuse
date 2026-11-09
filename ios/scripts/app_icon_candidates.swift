// Renders app icon candidates built on the driving robot (Shared/Robot.swift), with their dark and tinted
// variants, and a preview sheet (home screen at 60 pt, Settings at 29 pt, light and dark).
//   swiftc -parse-as-library ios/Shared/Robot.swift ios/scripts/app_icon_candidates.swift -o /tmp/icons
//   /tmp/icons OUT_DIR SHEET.png
import AppKit
import SwiftUI
import UniformTypeIdentifiers

enum Variant { case light, dark, tinted }

let blue = Color(red: 0.16, green: 0.42, blue: 1.0)
let purple = Color(red: 0.55, green: 0.24, blue: 1.0)
let brand = LinearGradient(colors: [blue, purple], startPoint: .topLeading, endPoint: .bottomTrailing)

/// The background for a variant: the brand gradient, near-black for dark, black for tinted (iOS tints the glyph).
struct Back: View {
    var variant: Variant
    var body: some View {
        switch variant {
        case .light:
            ZStack {
                brand
                RadialGradient(colors: [.white.opacity(0.22), .clear], center: UnitPoint(x: 0.3, y: 0.2),
                               startRadius: 0, endRadius: 700)
            }
        case .dark: LinearGradient(colors: [Color(white: 0.11), Color(white: 0.03)], startPoint: .top, endPoint: .bottom)
        case .tinted: Color.black
        }
    }
}

/// The glyph's fill: white on the gradient, the gradient on dark, light gray for tinted.
func glyphStyle(_ v: Variant) -> AnyShapeStyle {
    switch v {
    case .light: return AnyShapeStyle(Color.white)
    case .dark: return AnyShapeStyle(LinearGradient(colors: [Color(red: 0.35, green: 0.6, blue: 1), Color(red: 0.7, green: 0.45, blue: 1)],
                                                    startPoint: .topLeading, endPoint: .bottomTrailing))
    case .tinted: return AnyShapeStyle(Color(white: 0.92))
    }
}

/// The robot in a fill style: RobotView draws in one color, so it's used as a mask.
struct Robot: View {
    var size: CGFloat
    var style: AnyShapeStyle
    var body: some View {
        Rectangle().fill(style)
            .frame(width: size, height: size)
            .mask(RobotView(pose: RobotPose(), size: size, color: .white))
    }
}

/// 1. The robot head large and centered.
struct Icon1: View {
    var v: Variant
    var body: some View {
        ZStack {
            Back(variant: v)
            Robot(size: 700, style: glyphStyle(v))
                .shadow(color: .black.opacity(v == .light ? 0.25 : 0), radius: 30, y: 18)
                .offset(y: -10)
        }
    }
}

/// 2. The robot peeking over the top of a phone: the phone covers the lower part of its head.
struct Icon2: View {
    var v: Variant
    var body: some View {
        let body: Color = v == .light ? Color(red: 0.07, green: 0.09, blue: 0.24) : v == .dark ? Color(white: 0.22) : Color(white: 0.5)
        let screen: AnyShapeStyle = v == .light
            ? AnyShapeStyle(LinearGradient(colors: [Color(red: 0.55, green: 0.75, blue: 1), Color(red: 0.75, green: 0.6, blue: 1)],
                                           startPoint: .top, endPoint: .bottom))
            : v == .dark ? AnyShapeStyle(Color(white: 0.32)) : AnyShapeStyle(Color(white: 0.7))
        ZStack {
            Back(variant: v)
            Robot(size: 600, style: glyphStyle(v)).offset(y: -175)
            ZStack {
                RoundedRectangle(cornerRadius: 120, style: .continuous).fill(body)
                    .frame(width: 600, height: 640)
                RoundedRectangle(cornerRadius: 80, style: .continuous).fill(screen)
                    .frame(width: 500, height: 540)
            }
            .offset(y: 380)
            .shadow(color: .black.opacity(v == .light ? 0.35 : 0), radius: 26, y: -8)
        }
        .clipped()
    }
}

/// 3. The robot inside the Live Activity's ring.
struct Icon3: View {
    var v: Variant
    var body: some View {
        let ringStyle: AnyShapeStyle = v == .tinted ? AnyShapeStyle(Color(white: 0.92))
            : AnyShapeStyle(AngularGradient(colors: [blue.opacity(0.15), blue, purple], center: .center,
                                            startAngle: .degrees(0), endAngle: .degrees(260)))
        ZStack {
            if v == .light {
                LinearGradient(colors: [Color(red: 0.06, green: 0.08, blue: 0.2), Color(red: 0.12, green: 0.08, blue: 0.3)],
                               startPoint: .top, endPoint: .bottom)
            } else {
                Back(variant: v)
            }
            Circle()
                .trim(from: 0, to: 0.72)
                .stroke(ringStyle, style: StrokeStyle(lineWidth: 92, lineCap: .round))
                .frame(width: 700, height: 700)
                .rotationEffect(.degrees(-90))
            Robot(size: 430, style: v == .light ? AnyShapeStyle(Color.white) : glyphStyle(v)).offset(y: -8)
        }
    }
}

/// 4. The robot's head is a phone: a portrait phone with the robot's eyes and antenna.
struct Icon4: View {
    var v: Variant
    var body: some View {
        let style = glyphStyle(v)
        ZStack {
            Back(variant: v)
            ZStack {
                // Antenna
                Rectangle().frame(width: 64, height: 120).offset(y: -390)
                Circle().frame(width: 104, height: 104).offset(y: -450)
                // Phone-head with eyes cut out
                ZStack {
                    RoundedRectangle(cornerRadius: 120, style: .continuous).frame(width: 460, height: 700)
                    HStack(spacing: 110) {
                        Circle().frame(width: 96, height: 96)
                        Circle().frame(width: 96, height: 96)
                    }
                    .offset(y: -60)
                    .blendMode(.destinationOut)
                    // A small "home bar" as a smile, solid, not a hairline
                    Capsule().frame(width: 170, height: 40).offset(y: 230).blendMode(.destinationOut)
                }
                .compositingGroup()
                .offset(y: 60)
            }
            .foregroundStyle(style)
            .compositingGroup()
            .scaleEffect(0.82)
            .offset(y: 40)
            .shadow(color: .black.opacity(v == .light ? 0.25 : 0), radius: 30, y: 18)
        }
    }
}

func icon(_ n: Int, _ v: Variant) -> AnyView {
    let content: AnyView
    switch n {
    case 1: content = AnyView(Icon1(v: v))
    case 2: content = AnyView(Icon2(v: v))
    case 3: content = AnyView(Icon3(v: v))
    default: content = AnyView(Icon4(v: v))
    }
    return AnyView(content.frame(width: 1024, height: 1024).clipped())
}

/// An icon at `pt` points with the iOS continuous-corner mask.
struct Masked: View {
    var n: Int
    var v: Variant
    var pt: CGFloat
    var tint: Color? = nil
    var body: some View {
        ZStack {
            icon(n, v)
            if let tint { tint.blendMode(.multiply) }
        }
        .frame(width: 1024, height: 1024)
        .scaleEffect(pt / 1024)
        .frame(width: pt, height: pt)
        .clipShape(RoundedRectangle(cornerRadius: pt * 0.2237, style: .continuous))
    }
}

struct HomeScreen: View {
    var n: Int
    var dark: Bool
    var body: some View {
        ZStack {
            LinearGradient(colors: dark ? [Color(red: 0.08, green: 0.1, blue: 0.2), Color(red: 0.2, green: 0.08, blue: 0.25)]
                                        : [Color(red: 0.98, green: 0.82, blue: 0.7), Color(red: 0.75, green: 0.85, blue: 1)],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
            HStack(alignment: .top, spacing: 26) {
                ForEach(0..<3) { k in
                    VStack(spacing: 6) {
                        if k == 1 {
                            Masked(n: n, v: dark ? .dark : .light, pt: 60)
                        } else {
                            RoundedRectangle(cornerRadius: 60 * 0.2237, style: .continuous)
                                .fill(dark ? Color(white: 0.25) : Color.white.opacity(0.75)).frame(width: 60, height: 60)
                        }
                        Text(k == 1 ? "Phone Use" : " ").font(.system(size: 12, weight: .medium))
                            .foregroundStyle(dark ? .white : .black.opacity(0.8))
                    }
                }
            }
        }
        .frame(width: 280, height: 120)
        .clipShape(RoundedRectangle(cornerRadius: 18))
    }
}

struct SettingsRow: View {
    var n: Int
    var dark: Bool
    var body: some View {
        HStack(spacing: 12) {
            Masked(n: n, v: dark ? .dark : .light, pt: 29)
            Text("Phone Use").font(.system(size: 17)).foregroundStyle(dark ? .white : .black)
            Spacer()
            Image(systemName: "chevron.right").font(.system(size: 14, weight: .semibold)).foregroundStyle(.gray)
        }
        .padding(.horizontal, 16)
        .frame(width: 280, height: 44)
        .background(dark ? Color(white: 0.11) : .white)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

struct Sheet: View {
    var body: some View {
        let names = ["1  Robot on gradient", "2  Robot peeking over a phone", "3  Robot in the ring", "4  The phone is the robot"]
        VStack(alignment: .leading, spacing: 28) {
            Text("Phone Use icon candidates: master, dark, tinted (gray and a sample tint); home screen at 60 pt and Settings at 29 pt, light and dark")
                .font(.system(size: 15)).foregroundStyle(.gray)
            ForEach(1...4, id: \.self) { n in
                VStack(alignment: .leading, spacing: 10) {
                    Text(names[n - 1]).font(.system(size: 17, weight: .semibold)).foregroundStyle(.white)
                    HStack(alignment: .center, spacing: 22) {
                        Masked(n: n, v: .light, pt: 180)
                        Masked(n: n, v: .dark, pt: 120)
                        Masked(n: n, v: .tinted, pt: 120)
                        Masked(n: n, v: .tinted, pt: 120, tint: Color(red: 1, green: 0.62, blue: 0.3))
                        VStack(spacing: 10) {
                            HomeScreen(n: n, dark: false)
                            SettingsRow(n: n, dark: false)
                        }
                        VStack(spacing: 10) {
                            HomeScreen(n: n, dark: true)
                            SettingsRow(n: n, dark: true)
                        }
                    }
                }
            }
        }
        .padding(30)
        .background(Color(white: 0.06))
    }
}

@MainActor func save(_ view: some View, _ path: String, scale: CGFloat) {
    let r = ImageRenderer(content: view)
    r.scale = scale
    guard let cg = r.cgImage else { fatalError("render failed: \(path)") }
    let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, cg, nil)
    CGImageDestinationFinalize(dest)
}

@main
struct Main {
    @MainActor static func main() {
        let out = CommandLine.arguments[1], sheet = CommandLine.arguments[2]
        for n in 1...4 {
            for (v, name) in [(Variant.light, "light"), (.dark, "dark"), (.tinted, "tinted")] {
                save(icon(n, v), "\(out)/icon\(n)-\(name).png", scale: 1)
            }
        }
        save(Sheet(), sheet, scale: 2)
        print("done")
    }
}
