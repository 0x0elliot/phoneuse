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

    struct KeyStroke {
        let code: CGKeyCode
        let shift: Bool
    }

    /// US ANSI layout. iPhone Mirroring forwards hardware keycodes, so a
    /// CGEvent carrying only a unicode string arrives as the raw keycode.
    static let charMap: [Character: KeyStroke] = {
        var m: [Character: KeyStroke] = [:]
        let letters: [(Character, CGKeyCode)] = [
            ("a", 0), ("s", 1), ("d", 2), ("f", 3), ("h", 4), ("g", 5), ("z", 6),
            ("x", 7), ("c", 8), ("v", 9), ("b", 11), ("q", 12), ("w", 13), ("e", 14),
            ("r", 15), ("y", 16), ("t", 17), ("o", 31), ("u", 32), ("i", 34), ("p", 35),
            ("l", 37), ("j", 38), ("k", 40), ("n", 45), ("m", 46)
        ]
        for (ch, code) in letters {
            m[ch] = KeyStroke(code: code, shift: false)
            m[Character(ch.uppercased())] = KeyStroke(code: code, shift: true)
        }
        let digits: [(Character, CGKeyCode)] = [
            ("1", 18), ("2", 19), ("3", 20), ("4", 21), ("6", 22),
            ("5", 23), ("9", 25), ("7", 26), ("8", 28), ("0", 29)
        ]
        for (ch, code) in digits {
            m[ch] = KeyStroke(code: code, shift: false)
        }
        let plain: [(Character, CGKeyCode)] = [
            ("=", 24), ("-", 27), ("]", 30), ("[", 33), (";", 41), ("'", 39),
            ("\\", 42), (",", 43), ("/", 44), (".", 47), ("`", 50)
        ]
        for (ch, code) in plain {
            m[ch] = KeyStroke(code: code, shift: false)
        }
        let shifted: [(Character, CGKeyCode)] = [
            ("+", 24), ("_", 27), ("}", 30), ("{", 33), (":", 41), ("\"", 39),
            ("|", 42), ("<", 43), ("?", 44), (">", 47), ("~", 50),
            ("!", 18), ("@", 19), ("#", 20), ("$", 21), ("^", 22), ("%", 23),
            ("(", 25), ("&", 26), ("*", 28), (")", 29)
        ]
        for (ch, code) in shifted {
            m[ch] = KeyStroke(code: code, shift: true)
        }
        m[" "] = KeyStroke(code: 49, shift: false)
        m["\n"] = KeyStroke(code: 36, shift: false)
        m["\t"] = KeyStroke(code: 48, shift: false)
        return m
    }()

    static let modifierCodes: [String: CGKeyCode] = [
        "cmd": 55, "command": 55, "shift": 56, "alt": 58, "option": 58,
        "ctrl": 59, "control": 59
    ]

    /// Post a key with real modifier key-down/up events. iPhone Mirroring reads
    /// hardware key state, so setting CGEvent.flags alone is ignored.
    static func postKey(_ code: CGKeyCode, modifiers: [CGKeyCode] = []) {
        let src = CGEventSource(stateID: .hidSystemState)
        for m in modifiers {
            CGEvent(keyboardEventSource: src, virtualKey: m, keyDown: true)?.post(tap: .cghidEventTap)
            Thread.sleep(forTimeInterval: 0.012)
        }
        CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true)?.post(tap: .cghidEventTap)
        Thread.sleep(forTimeInterval: 0.012)
        CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)?.post(tap: .cghidEventTap)
        for m in modifiers.reversed() {
            Thread.sleep(forTimeInterval: 0.012)
            CGEvent(keyboardEventSource: src, virtualKey: m, keyDown: false)?.post(tap: .cghidEventTap)
        }
        Thread.sleep(forTimeInterval: 0.012)
    }

    static func send(_ stroke: KeyStroke) {
        postKey(stroke.code, modifiers: stroke.shift ? [modifierCodes["shift"]!] : [])
    }

    static func selectAll() {
        postKey(0, modifiers: [modifierCodes["cmd"]!])
    }

    static func type(_ text: String) {
        for ch in text {
            if let stroke = charMap[ch] {
                send(stroke)
            } else {
                // Fallback for anything not on a US keyboard (emoji, accents).
                let src = CGEventSource(stateID: .hidSystemState)
                for unit in String(ch).utf16 {
                    var c = unit
                    let down = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: true)
                    down?.keyboardSetUnicodeString(stringLength: 1, unicodeString: &c)
                    down?.post(tap: .cghidEventTap)
                    let up = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: false)
                    up?.keyboardSetUnicodeString(stringLength: 1, unicodeString: &c)
                    up?.post(tap: .cghidEventTap)
                }
                Thread.sleep(forTimeInterval: 0.012)
            }
        }
    }

    static let keyCodes: [String: CGKeyCode] = [
        "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
        "escape": 53, "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126,
        "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
        // ANSI letters
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
        "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32,
        "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
        // digits
        "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29,
        // punctuation and brackets
        "=": 24, "-": 27, "]": 30, "[": 33, "'": 39, ";": 41, "\\": 42, ",": 43, "/": 44,
        ".": 47, "`": 50
    ]

    /// "cmd+h", "shift+tab", "enter", "escape".
    static func key(_ combo: String) throws {
        let parts = combo.lowercased().split(separator: "+").map(String.init)
        guard let last = parts.last, let code = keyCodes[last] else {
            throw PUError.usage("unknown key: \(combo). Try enter, escape, tab, space, delete, up, down, left, right, or a combo like cmd+h.")
        }
        var mods: [CGKeyCode] = []
        for mod in parts.dropLast() {
            guard let m = modifierCodes[mod] else {
                throw PUError.usage("unknown modifier: \(mod)")
            }
            mods.append(m)
        }
        postKey(code, modifiers: mods)
    }
}
