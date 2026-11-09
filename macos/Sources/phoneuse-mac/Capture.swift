import AppKit
import CoreGraphics
import Foundation

struct Frame {
    let image: CGImage
    let window: PhoneWindow
    /// Points of chrome (title bar) cropped off the top of the window.
    let cropTopPoints: CGFloat
    /// Pixels per point (Retina is 2).
    let scale: CGFloat

    var width: CGFloat { CGFloat(image.width) }
    var height: CGFloat { CGFloat(image.height) }
}

enum Capture {
    static func grab(_ w: PhoneWindow) throws -> Frame {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("phoneuse-mac-\(UUID().uuidString).png")
        defer { try? FileManager.default.removeItem(at: tmp) }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        p.arguments = ["-x", "-o", "-l", String(w.id), tmp.path]
        p.standardError = Pipe()
        p.standardOutput = Pipe()
        do { try p.run() } catch {
            throw PUError.capture(error.localizedDescription)
        }
        p.waitUntilExit()
        guard p.terminationStatus == 0 else {
            throw PUError.capture("screencapture exited \(p.terminationStatus)")
        }
        guard let ns = NSImage(contentsOf: tmp) else {
            throw PUError.capture("no image written")
        }
        var rect = CGRect(origin: .zero, size: ns.size)
        guard let cg = ns.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
            throw PUError.capture("unreadable image")
        }

        let scale = CGFloat(cg.width) / max(w.bounds.width, 1)
        let cropPx = cropOverridePixels(scale: scale) ?? detectCropTop(cg)
        let safeCrop = min(cropPx, cg.height / 5)
        let cropped = cg.cropping(
            to: CGRect(x: 0, y: safeCrop, width: cg.width, height: cg.height - safeCrop)
        ) ?? cg

        return Frame(
            image: cropped,
            window: w,
            cropTopPoints: CGFloat(safeCrop) / scale,
            scale: scale
        )
    }

    /// `PHONEUSE_MAC_CROP_TOP=<points>` overrides the automatic title-bar detection.
    private static func cropOverridePixels(scale: CGFloat) -> Int? {
        guard let raw = ProcessInfo.processInfo.environment["PHONEUSE_MAC_CROP_TOP"],
              let points = Double(raw) else { return nil }
        return Int(points * Double(scale))
    }

    /// The iPhone Mirroring window has a slim title bar; find the first row that
    /// stops looking like that uniform bar. Cap the result so we never eat content.
    static func detectCropTop(_ img: CGImage) -> Int {
        let w = img.width, h = img.height
        guard w > 8, h > 8 else { return 0 }
        let bytesPerRow = w * 4
        var buf = [UInt8](repeating: 0, count: bytesPerRow * h)
        let cs = CGColorSpaceCreateDeviceRGB()
        let ok = buf.withUnsafeMutableBytes { raw -> Bool in
            guard let ctx = CGContext(
                data: raw.baseAddress, width: w, height: h, bitsPerComponent: 8,
                bytesPerRow: bytesPerRow, space: cs,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ) else { return false }
            ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        guard ok else { return 0 }

        func average(yFromTop i: Int) -> (Int, Int, Int) {
            let y = h - 1 - i
            var r = 0, g = 0, b = 0, n = 0
            var x = 2
            while x < w - 2 {
                let o = y * bytesPerRow + x * 4
                r += Int(buf[o]); g += Int(buf[o + 1]); b += Int(buf[o + 2])
                n += 1
                x += 8
            }
            return n == 0 ? (0, 0, 0) : (r / n, g / n, b / n)
        }

        let top = average(yFromTop: 0)
        let limit = min(h / 5, 320)
        for i in 1..<max(limit, 1) {
            let c = average(yFromTop: i)
            let delta = abs(c.0 - top.0) + abs(c.1 - top.1) + abs(c.2 - top.2)
            if delta > 30 { return i }
        }
        return 0
    }
}
