import CoreGraphics
import Foundation

enum Input {
    /// Convert a fraction of the phone screen (0..1, origin top-left) to a global point.
    static func point(nx: Double, ny: Double, in frame: Frame) -> CGPoint {
        let b = frame.window.bounds
        let contentHeight = b.height - frame.cropTopPoints
        return CGPoint(
            x: b.minX + CGFloat(nx) * b.width,
            y: b.minY + frame.cropTopPoints + CGFloat(ny) * contentHeight
        )
    }

    static func point(in frame: Frame, pixelRect r: CGRect) -> CGPoint {
        point(
            nx: Double(r.midX / frame.width),
            ny: Double(r.midY / frame.height),
            in: frame
        )
    }

    static func click(_ p: CGPoint, hold: TimeInterval = 0.05) {
        let src = CGEventSource(stateID: .hidSystemState)
        let down = CGEvent(mouseEventSource: src, mouseType: .leftMouseDown,
                           mouseCursorPosition: p, mouseButton: .left)
        let up = CGEvent(mouseEventSource: src, mouseType: .leftMouseUp,
                         mouseCursorPosition: p, mouseButton: .left)
        down?.post(tap: .cghidEventTap)
        Thread.sleep(forTimeInterval: hold)
        up?.post(tap: .cghidEventTap)
    }

    static func swipe(from a: CGPoint, to b: CGPoint, seconds: Double) {
        let src = CGEventSource(stateID: .hidSystemState)
        let steps = max(Int(seconds * 60), 8)
        CGEvent(mouseEventSource: src, mouseType: .leftMouseDown,
                mouseCursorPosition: a, mouseButton: .left)?.post(tap: .cghidEventTap)
        for i in 1...steps {
            let t = Double(i) / Double(steps)
            let p = CGPoint(x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t)
            CGEvent(mouseEventSource: src, mouseType: .leftMouseDragged,
                    mouseCursorPosition: p, mouseButton: .left)?.post(tap: .cghidEventTap)
            Thread.sleep(forTimeInterval: seconds / Double(steps))
        }
        CGEvent(mouseEventSource: src, mouseType: .leftMouseUp,
                mouseCursorPosition: b, mouseButton: .left)?.post(tap: .cghidEventTap)
    }

    static func type(_ text: String) {
        let src = CGEventSource(stateID: .hidSystemState)
        for unit in text.utf16 {
            var c = unit
            let down = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: true)
            down?.keyboardSetUnicodeString(stringLength: 1, unicodeString: &c)
            down?.post(tap: .cghidEventTap)
            let up = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: false)
            up?.keyboardSetUnicodeString(stringLength: 1, unicodeString: &c)
            up?.post(tap: .cghidEventTap)
            Thread.sleep(forTimeInterval: 0.008)
        }
    }

    static let keyCodes: [String: CGKeyCode] = [
        "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
        "escape": 53, "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126,
        "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97
    ]

    static let modifierFlags: [String: CGEventFlags] = [
        "cmd": .maskCommand, "command": .maskCommand,
        "shift": .maskShift,
        "alt": .maskAlternate, "option": .maskAlternate,
        "ctrl": .maskControl, "control": .maskControl
    ]

    /// "cmd+h", "shift+tab", "enter", "escape".
    static func key(_ combo: String) throws {
        let parts = combo.lowercased().split(separator: "+").map(String.init)
        guard let last = parts.last, let code = keyCodes[last] else {
            throw PUError.usage("unknown key: \(combo). Try enter, escape, tab, space, delete, up, down, left, right, or a combo like cmd+h.")
        }
        var flags: CGEventFlags = []
        for mod in parts.dropLast() {
            guard let f = modifierFlags[mod] else {
                throw PUError.usage("unknown modifier: \(mod)")
            }
            flags.insert(f)
        }
        let src = CGEventSource(stateID: .hidSystemState)
        let down = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true)
        down?.flags = flags
        down?.post(tap: .cghidEventTap)
        let up = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)
        up?.flags = flags
        up?.post(tap: .cghidEventTap)
    }
}
