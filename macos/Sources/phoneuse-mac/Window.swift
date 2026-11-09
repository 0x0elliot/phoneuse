import CoreGraphics
import Foundation

enum PUError: Error, CustomStringConvertible {
    case noWindow
    case capture(String)
    case usage(String)
    case notFound(String)
    case permission(String)

    var description: String {
        switch self {
        case .noWindow:
            return "no iPhone Mirroring window. Open the iPhone Mirroring app and pair your phone (same Apple ID, phone locked, Bluetooth and Wi-Fi on)."
        case .capture(let detail):
            return "could not capture the window (\(detail)). Grant Screen Recording to your terminal in System Settings › Privacy & Security › Screen Recording."
        case .usage(let detail):
            return detail
        case .notFound(let text):
            return "not on screen: \"\(text)\". Scroll or take a screenshot and tap by position."
        case .permission(let detail):
            return detail
        }
    }
}

struct PhoneWindow {
    let id: CGWindowID
    let bounds: CGRect
}

enum WindowFinder {
    static func find() throws -> PhoneWindow {
        let opts: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let list = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]] else {
            throw PUError.noWindow
        }
        for w in list {
            guard let owner = w[kCGWindowOwnerName as String] as? String else { continue }
            guard owner == "iPhone Mirroring" else { continue }
            guard let b = w[kCGWindowBounds as String] as? [String: Any],
                  let x = b["X"] as? Double, let y = b["Y"] as? Double,
                  let width = b["Width"] as? Double, let height = b["Height"] as? Double,
                  let num = w[kCGWindowNumber as String] as? Int
            else { continue }
            if width < 200 || height < 200 { continue }
            return PhoneWindow(
                id: CGWindowID(num),
                bounds: CGRect(x: x, y: y, width: width, height: height)
            )
        }
        throw PUError.noWindow
    }

    static func isRunning() -> Bool {
        NSWorkspaceBridge.isPhoneMirroringRunning()
    }

    static func activate() {
        NSWorkspaceBridge.activatePhoneMirroring()
    }
}
