// Renders the driving robot's animation to PNG frames with the real SwiftUI view (Shared/Robot.swift), blending
// poses the way iOS animates them: each 1 s update eases in and out over 0.9 s, and the ring turns 45 degrees
// linearly per update. Build and run:
//   swiftc -parse-as-library ios/Shared/Robot.swift ios/scripts/robot_preview.swift -o /tmp/robot_preview
//   /tmp/robot_preview OUT_DIR
import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The widget's ring, copied: a 0.72 trim with a fading tail, turned by `angle`.
struct Ring: View {
    var size: CGFloat
    var color: Color
    var angle: Double

    var body: some View {
        Circle()
            .trim(from: 0, to: 0.72)
            .stroke(AngularGradient(colors: [color.opacity(0.05), color], center: .center,
                                    startAngle: .degrees(0), endAngle: .degrees(260)),
                    style: StrokeStyle(lineWidth: max(2, size * 0.09), lineCap: .round))
            .padding(size * 0.06)
            .rotationEffect(.degrees(angle))
            .frame(width: size, height: size)
    }
}

struct Icon: View {
    var size: CGFloat
    var color: Color
    var angle: Double
    var pose: RobotPose

    var body: some View {
        ZStack {
            Ring(size: size, color: color, angle: angle)
            RobotView(pose: pose, size: size * 0.58, color: color)
        }
        .frame(width: size, height: size)
    }
}

struct Frame: View {
    var phase: String
    var t: Double

    var body: some View {
        let color: Color = phase == "thinking" ? .purple : .blue
        let k = Int(floor(t))
        let u = min((t - Double(k)) / 0.9, 1)
        let pose = RobotPose.mix(RobotPose.pose(phase: phase, frame: k - 1), RobotPose.pose(phase: phase, frame: k),
                                 CGFloat(easeInOut(u)))
        let angle = 45 * (Double(k - 1) + min(t - Double(k), 1))
        let title = ["thinking": "Agent is thinking", "reading": "Agent is reading", "acting": "Agent is tapping"][phase]!
        HStack(spacing: 28) {
            HStack(spacing: 12) {
                Icon(size: 44, color: color, angle: angle, pose: pose)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.system(size: 17, weight: .semibold)).foregroundStyle(.white)
                    Text("Opening Settings · 3 steps").font(.system(size: 15)).foregroundStyle(.gray)
                }
            }
            VStack(spacing: 6) {
                Icon(size: 22, color: color, angle: angle, pose: pose)
                Text("compact").font(.system(size: 10)).foregroundStyle(.gray)
            }
        }
        .padding(20)
        .frame(width: 420, height: 110)
        .background(.black)
    }
}

/// SwiftUI's easeInOut: a cubic Bezier with control points (0.42, 0) and (0.58, 1).
func easeInOut(_ x: Double) -> Double {
    func bez(_ t: Double, _ p1: Double, _ p2: Double) -> Double {
        let u = 1 - t
        return 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t
    }
    var lo = 0.0, hi = 1.0
    for _ in 0..<40 {
        let mid = (lo + hi) / 2
        if bez(mid, 0.42, 0.58) < x { lo = mid } else { hi = mid }
    }
    return bez((lo + hi) / 2, 0, 1)
}

@main
struct Main {
    @MainActor static func main() {
        let out = CommandLine.arguments[1]
        var n = 0
        for phase in ["thinking", "reading", "acting"] {
            for f in 0..<(8 * 30) {
                let r = ImageRenderer(content: Frame(phase: phase, t: 1 + Double(f) / 30))
                r.scale = 3
                guard let cg = r.cgImage else { fatalError("render failed") }
                let url = URL(fileURLWithPath: "\(out)/f\(String(format: "%04d", n)).png")
                let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
                CGImageDestinationAddImage(dest, cg, nil)
                CGImageDestinationFinalize(dest)
                n += 1
            }
        }
        print("rendered \(n) frames")
    }
}
