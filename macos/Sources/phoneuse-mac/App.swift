import AppKit
import ApplicationServices

enum NSWorkspaceBridge {
    static func isPhoneMirroringRunning() -> Bool {
        !apps().isEmpty
    }

    static func activatePhoneMirroring() {
        for app in apps() {
            app.activate()
        }
    }

    private static func apps() -> [NSRunningApplication] {
        NSWorkspace.shared.runningApplications.filter { app in
            if app.localizedName == "iPhone Mirroring" { return true }
            if let id = app.bundleIdentifier,
               id.localizedCaseInsensitiveContains("mirroring") || id.localizedCaseInsensitiveContains("continuity") {
                return true
            }
            return false
        }
    }
}

enum Permissions {
    static var accessibility: Bool { AXIsProcessTrusted() }

    static func requireAccessibility() throws {
        guard accessibility else {
            throw PUError.permission(
                "Accessibility is not granted, so clicks and keystrokes will not reach the phone. "
                + "Grant it to your terminal in System Settings › Privacy & Security › Accessibility, then restart the terminal."
            )
        }
    }
}
