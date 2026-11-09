import AppKit
import Foundation
import ImageIO
import UniformTypeIdentifiers

let version = "0.1.0"

let usageText = """
phoneuse-mac \(version) — drive an iPhone from a MacBook, over iPhone Mirroring

USAGE
  phoneuse-mac status
  phoneuse-mac screenshot [PATH]
  phoneuse-mac text [--json] [--all]
  phoneuse-mac tap <x> <y> [--text]
  phoneuse-mac longpress <x> <y> [seconds] [--text]
  phoneuse-mac tap-on "<words>" [--text]
  phoneuse-mac type "<text>" [--append] [--text]
  phoneuse-mac key <combo> [--text]          e.g. enter, escape, cmd+h
  phoneuse-mac swipe <x0> <y0> <x1> <y1> [seconds] [--text]
  phoneuse-mac scroll up|down [screens] [--text]
  phoneuse-mac home [--text]
  phoneuse-mac back [--text]
  phoneuse-mac open "<App Name>" [--text]
  phoneuse-mac done

Coordinates are fractions of the phone screen (0..1), origin top-left.

REQUIRES
  iPhone Mirroring open and paired; Screen Recording and Accessibility
  granted to the terminal running this command.

ENV
  PHONEUSE_MAC_CROP_TOP   points of window chrome to crop (default: auto)
"""

func fail(_ error: Error) -> Never {
    FileHandle.standardError.write(Data("phoneuse-mac: \(error)\n".utf8))
    exit(1)
}

// MARK: - shared helpers

func currentFrame() throws -> Frame {
    let w = try WindowFinder.find()
    return try Capture.grab(w)
}

func screenText(_ frame: Frame, all: Bool) -> [TextLine] {
    var lines = (try? OCR.lines(frame.image)) ?? []
    if !all {
        // Drop the clock/battery strip at the very top, like the Linux CLI does.
        lines = lines.filter { $0.rect.midY / frame.height > 0.03 }
    }
    return lines
}

func printText(_ frame: Frame, all: Bool, json: Bool) {
    let lines = screenText(frame, all: all)
    if json {
        let payload: [[String: Any]] = lines.map { line in
            [
                "text": line.text,
                "x": Double(line.rect.midX / frame.width),
                "y": Double(line.rect.midY / frame.height)
            ]
        }
        if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted]),
           let s = String(data: data, encoding: .utf8) {
            print(s)
        }
        return
    }
    for line in lines {
        let x = line.rect.midX / frame.width
        let y = line.rect.midY / frame.height
        print(String(format: "%.3f %.3f  %@", x, y, line.text))
    }
}

func afterAction(_ wantsText: Bool, all: Bool = false) {
    guard wantsText else { return }
    Thread.sleep(forTimeInterval: 0.8)
    do {
        printText(try currentFrame(), all: all, json: false)
    } catch {
        FileHandle.standardError.write(Data("phoneuse-mac: (could not read the screen: \(error))\n".utf8))
    }
}

func writePNG(_ image: CGImage, to path: String) throws {
    let url = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
    guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
        throw PUError.usage("could not write \(path)")
    }
    CGImageDestinationAddImage(dest, image, nil)
    guard CGImageDestinationFinalize(dest) else {
        throw PUError.usage("could not write \(path)")
    }
}

func doubleArg(_ s: String, _ name: String) throws -> Double {
    guard let v = Double(s) else { throw PUError.usage("\(name) must be a number, got \"\(s)\"") }
    return v
}

// MARK: - commands

func runStatus() throws {
    guard WindowFinder.isRunning() else {
        print("iPhone Mirroring: not running")
        print("ready: no — open the app and pair your phone")
        exit(1)
    }
    let w = try WindowFinder.find()
    print("iPhone Mirroring: window \(w.id) at \(Int(w.bounds.minX)),\(Int(w.bounds.minY)) size \(Int(w.bounds.width))x\(Int(w.bounds.height))")

    do {
        let f = try Capture.grab(w)
        print("capture: ok (\(Int(f.width))x\(Int(f.height)) px, \(String(format: "%.0f", f.scale))x, chrome cropped \(String(format: "%.0f", f.cropTopPoints)) pt)")
        let lines = screenText(f, all: false)
        print("screen text: \(lines.count) lines")
        if let first = lines.first { print("first line: \(first.text)") }
    } catch {
        print("capture: FAILED — \(error)")
    }

    print("accessibility: \(Permissions.accessibility ? "granted" : "NOT granted — clicks and typing will not reach the phone")")
    let front = NSWorkspace.shared.frontmostApplication?.localizedName ?? "?"
    print("frontmost app: \(front)")
    print("ready: \(Permissions.accessibility ? "yes" : "no")")
}

func runScreenshot(_ path: String?) throws {
    let frame = try currentFrame()
    let target = path ?? FileManager.default.temporaryDirectory
        .appendingPathComponent("phoneuse-mac-\(Int(Date().timeIntervalSince1970)).png").path
    try writePNG(frame.image, to: target)
    print(target)
}

func runText(all: Bool, json: Bool) throws {
    printText(try currentFrame(), all: all, json: json)
}

func runTap(_ x: Double, _ y: Double, wantsText: Bool) throws {
    try Permissions.requireAccessibility()
    let frame = try currentFrame()
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.25)
    Input.click(Input.point(nx: x, ny: y, in: frame))
    afterAction(wantsText)
}

func runLongPress(_ x: Double, _ y: Double, _ seconds: Double, wantsText: Bool) throws {
    try Permissions.requireAccessibility()
    let frame = try currentFrame()
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.25)
    Input.click(Input.point(nx: x, ny: y, in: frame), hold: seconds)
    afterAction(wantsText)
}

func runTapOn(_ words: String, wantsText: Bool) throws {
    try Permissions.requireAccessibility()
    let frame = try currentFrame()
    let lines = screenText(frame, all: true)
    guard let hit = OCR.find(words, in: lines) else { throw PUError.notFound(words) }
    let p = Input.point(in: frame, pixelRect: hit.rect)
    let nx = hit.rect.midX / frame.width
    let ny = hit.rect.midY / frame.height
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.25)
    Input.click(p)
    print(String(format: "tapped %.3f %.3f  \"%@\"", nx, ny, hit.text))
    afterAction(wantsText)
}

func runType(_ text: String, append: Bool, wantsText: Bool) throws {
    try Permissions.requireAccessibility()
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.25)
    if !append {
        try Input.key("cmd+a")
        Thread.sleep(forTimeInterval: 0.05)
    }
    Input.type(text)
    afterAction(wantsText)
}

func runSwipe(_ x0: Double, _ y0: Double, _ x1: Double, _ y1: Double, _ seconds: Double, wantsText: Bool) throws {
    try Permissions.requireAccessibility()
    let frame = try currentFrame()
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.25)
    Input.swipe(
        from: Input.point(nx: x0, ny: y0, in: frame),
        to: Input.point(nx: x1, ny: y1, in: frame),
        seconds: max(seconds, 0.1)
    )
    afterAction(wantsText)
}

func runScroll(_ direction: String, _ screens: Double, wantsText: Bool) throws {
    try Permissions.requireAccessibility()
    let frame = try currentFrame()
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.25)
    let start: Double, end: Double
    switch direction {
    case "down": start = 0.75; end = 0.75 - 0.45 * max(screens, 0.1)
    case "up": start = 0.25; end = 0.25 + 0.45 * max(screens, 0.1)
    default: throw PUError.usage("scroll takes up or down")
    }
    Input.swipe(
        from: Input.point(nx: 0.5, ny: start, in: frame),
        to: Input.point(nx: 0.5, ny: end, in: frame),
        seconds: 0.25
    )
    afterAction(wantsText)
}

func runHome(wantsText: Bool) throws {
    try Permissions.requireAccessibility()
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.2)
    let combo = ProcessInfo.processInfo.environment["PHONEUSE_MAC_HOME_COMBO"] ?? "cmd+shift+h"
    try Input.key(combo)
    afterAction(wantsText)
}

func runBack(wantsText: Bool) throws {
    try Permissions.requireAccessibility()
    let frame = try currentFrame()
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.2)
    Input.swipe(
        from: Input.point(nx: 0.01, ny: 0.5, in: frame),
        to: Input.point(nx: 0.75, ny: 0.5, in: frame),
        seconds: 0.25
    )
    afterAction(wantsText)
}

func runOpen(_ app: String, wantsText: Bool) throws {
    try runHome(wantsText: false)
    Thread.sleep(forTimeInterval: 1.0)
    let frame = try currentFrame()
    let lines = screenText(frame, all: true)
    guard let hit = OCR.find(app, in: lines) else {
        throw PUError.notFound("\(app) icon on the Home Screen")
    }
    WindowFinder.activate()
    Thread.sleep(forTimeInterval: 0.2)
    Input.click(Input.point(in: frame, pixelRect: hit.rect))
    afterAction(wantsText)
}

// MARK: - dispatch

let argv = Array(CommandLine.arguments.dropFirst())
guard let command = argv.first else {
    print(usageText)
    exit(2)
}

let flags = Set(argv.filter { $0.hasPrefix("--") })
let positional = argv.dropFirst().filter { !$0.hasPrefix("--") }
let wantsText = flags.contains("--text")

do {
    switch command {
    case "status":
        try runStatus()

    case "screenshot":
        try runScreenshot(positional.first)

    case "text":
        try runText(all: flags.contains("--all"), json: flags.contains("--json"))

    case "tap":
        guard positional.count >= 2 else { throw PUError.usage("tap needs x and y") }
        try runTap(try doubleArg(positional[0], "x"), try doubleArg(positional[1], "y"), wantsText: wantsText)

    case "longpress":
        guard positional.count >= 2 else { throw PUError.usage("longpress needs x and y") }
        let seconds = positional.count > 2 ? try doubleArg(positional[2], "seconds") : 0.8
        try runLongPress(try doubleArg(positional[0], "x"), try doubleArg(positional[1], "y"), seconds, wantsText: wantsText)

    case "tap-on":
        guard let words = positional.first else { throw PUError.usage("tap-on needs words") }
        try runTapOn(words, wantsText: wantsText)

    case "type":
        guard let text = positional.first else { throw PUError.usage("type needs text") }
        try runType(text, append: flags.contains("--append"), wantsText: wantsText)

    case "key":
        guard let combo = positional.first else { throw PUError.usage("key needs a combo") }
        try Permissions.requireAccessibility()
        WindowFinder.activate()
        Thread.sleep(forTimeInterval: 0.2)
        try Input.key(combo)
        afterAction(wantsText)

    case "swipe":
        guard positional.count >= 4 else { throw PUError.usage("swipe needs x0 y0 x1 y1") }
        let seconds = positional.count > 4 ? try doubleArg(positional[4], "seconds") : 0.3
        try runSwipe(
            try doubleArg(positional[0], "x0"), try doubleArg(positional[1], "y0"),
            try doubleArg(positional[2], "x1"), try doubleArg(positional[3], "y1"),
            seconds, wantsText: wantsText
        )

    case "scroll":
        guard let dir = positional.first else { throw PUError.usage("scroll needs up or down") }
        let screens = positional.count > 1 ? try doubleArg(positional[1], "screens") : 1.0
        try runScroll(dir, screens, wantsText: wantsText)

    case "home":
        try runHome(wantsText: wantsText)

    case "back":
        try runBack(wantsText: wantsText)

    case "open":
        guard let app = positional.first else { throw PUError.usage("open needs an app name") }
        try runOpen(app, wantsText: wantsText)

    case "done":
        WindowFinder.activate()
        print("Control is back with you. The phone is still mirroring.")

    case "--help", "help", "-h":
        print(usageText)

    default:
        print(usageText)
        exit(2)
    }
} catch {
    fail(error)
}
