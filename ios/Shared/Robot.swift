import SwiftUI

/// The driving robot: a solid head with cut-out eyes and an antenna, at one weight. Only transforms and opacities
/// change between poses, so its weights never change. The PC's 1 s refreshes count `frame` up; each phase is an
/// 8-step loop (frame % 8), and iOS animates between successive poses with `RobotPose.animation`.
struct RobotPose: Equatable {
    var eyeX: CGFloat = 0          // eye offset, in units of the glyph size
    var eyeY: CGFloat = 0
    var eyeScaleY: CGFloat = 1     // 0.15 for a blink
    var tilt: Double = 0           // degrees, around the head's bottom
    var drop: CGFloat = 0          // downward offset, in units of the glyph size
    var ballOpacity: Double = 1
    var barX: CGFloat = 0          // the reading scan bar's offset across the head
    var barOpacity: Double = 0
    var rippleScale: CGFloat = 0.4
    var rippleOpacity: Double = 0

    static let animation = Animation.easeInOut(duration: 0.9)

    /// The pose for a driving phase ("thinking", "reading", "acting") at step frame % 8.
    static func pose(phase: String?, frame: Int) -> RobotPose {
        let i = ((frame % 8) + 8) % 8
        var p = RobotPose()
        switch phase {
        case "reading":
            // Scan a line left to right, drop to the next line and scan again, then back to the top.
            let xs: [CGFloat] = [-0.07, 0, 0.07, -0.07, 0, 0.07, 0, -0.07]
            let ys: [CGFloat] = [-0.03, -0.03, -0.03, 0.03, 0.03, 0.03, 0, -0.03]
            p.eyeX = xs[i]
            p.eyeY = ys[i]
            p.barX = [-0.2, 0, 0.2, -0.2, 0, 0.2, 0, -0.2][i]
            p.barOpacity = [0, 1, 1, 0, 1, 1, 0, 0][i]
        case "acting":
            // Lean in and tap, twice per loop: a ripple grows from the lower right and fades.
            let s = i % 4
            p.eyeX = 0.05
            p.eyeY = 0.05
            p.tilt = s == 1 || s == 2 ? 8 : 0
            p.drop = s == 1 || s == 2 ? 0.05 : 0
            p.rippleScale = s == 2 ? 1.25 : 0.4
            p.rippleOpacity = s == 1 ? 1 : 0
        default:  // thinking
            // Eyes drift up-left, up-right, center; a blink every 4 steps; the ball pulses; the head tilts.
            let xs: [CGFloat] = [-0.06, 0.06, 0, 0, -0.06, 0.06, 0, 0]
            let ys: [CGFloat] = [-0.05, -0.05, 0, 0, -0.05, -0.05, 0, 0]
            p.eyeX = xs[i]
            p.eyeY = ys[i]
            p.eyeScaleY = i % 4 == 3 ? 0.15 : 1
            p.ballOpacity = i % 2 == 0 ? 1 : 0.5
            p.tilt = [-6, 0, 6, 0, -6, 0, 6, 0][i]
        }
        return p
    }

    /// The pose part way from `a` to `b` (t from 0 to 1), as an animation would draw it.
    static func mix(_ a: RobotPose, _ b: RobotPose, _ t: CGFloat) -> RobotPose {
        func m(_ x: CGFloat, _ y: CGFloat) -> CGFloat { x + (y - x) * t }
        func d(_ x: Double, _ y: Double) -> Double { x + (y - x) * Double(t) }
        return RobotPose(eyeX: m(a.eyeX, b.eyeX), eyeY: m(a.eyeY, b.eyeY), eyeScaleY: m(a.eyeScaleY, b.eyeScaleY),
                         tilt: d(a.tilt, b.tilt), drop: m(a.drop, b.drop), ballOpacity: d(a.ballOpacity, b.ballOpacity),
                         barX: m(a.barX, b.barX), barOpacity: d(a.barOpacity, b.barOpacity),
                         rippleScale: m(a.rippleScale, b.rippleScale),
                         rippleOpacity: d(a.rippleOpacity, b.rippleOpacity))
    }
}

struct RobotView: View {
    var pose: RobotPose
    var size: CGFloat
    var color: Color

    var body: some View {
        let s = size
        let stroke = s * 0.095          // Semibold's stroke on a 100-unit grid
        let stalk = stroke * 1.2
        let headW = s * 0.68, headH = s * 0.54
        let headY = s * 0.63            // head center
        let eye = stalk * 1.05
        ZStack {
            // Ripple (acting): a ring as thick as the stalk, from the lower right.
            Circle()
                .stroke(color, lineWidth: stalk * 0.8)
                .frame(width: s * 0.42, height: s * 0.42)
                .scaleEffect(pose.rippleScale)
                .opacity(pose.rippleOpacity)
                .position(x: s * 0.86, y: s * 0.9)
            Group {
                // Antenna: stalk and ball.
                Rectangle()
                    .fill(color)
                    .frame(width: stalk, height: headH * 0.3 + 2)
                    .position(x: s / 2, y: headY - headH / 2 - headH * 0.15)
                Circle()
                    .fill(color)
                    .frame(width: stalk * 1.6, height: stalk * 1.6)
                    .opacity(pose.ballOpacity)
                    .position(x: s / 2, y: headY - headH / 2 - headH * 0.3)
                // Head with eyes (and the reading bar) cut out.
                ZStack {
                    RoundedRectangle(cornerRadius: headW * 0.24, style: .continuous)
                        .fill(color)
                        .frame(width: headW, height: headH)
                    Group {
                        Circle().frame(width: eye, height: eye).offset(x: -headW * 0.17)
                        Circle().frame(width: eye, height: eye).offset(x: headW * 0.17)
                    }
                    .scaleEffect(x: 1, y: pose.eyeScaleY)
                    .offset(x: pose.eyeX * s, y: pose.eyeY * s - headH * 0.04)
                    .blendMode(.destinationOut)
                    Capsule()
                        .frame(width: stalk * 0.8, height: headH * 0.78)
                        .offset(x: pose.barX * s)
                        .opacity(pose.barOpacity)
                        .blendMode(.destinationOut)
                }
                .compositingGroup()
                .position(x: s / 2, y: headY)
            }
            .rotationEffect(.degrees(pose.tilt), anchor: UnitPoint(x: 0.5, y: 0.9))
            .offset(y: pose.drop * s)
        }
        .frame(width: s, height: s)
    }
}
