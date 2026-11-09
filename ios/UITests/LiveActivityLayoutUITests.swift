import XCTest

/// A design check, not a regression test: shows each Live Activity state (the app's DEBUG -PUDemo flag) on the
/// simulator's lock screen and attaches a screenshot. The simulator draws the lock screen once and doesn't animate
/// it, and it doesn't capture the Dynamic Island, so motion and the island need the phone.
final class LiveActivityLayoutUITests: XCTestCase {
    func testStateLayouts() throws {
        for state in ["idle", "warning", "delay", "asking", "driving", "paused"] {
            let app = XCUIApplication()
            app.launchArguments = ["-PUDemo", state]
            app.launch()
            sleep(3)
            XCUIDevice.shared.press(.home)
            sleep(1)
            XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
            sleep(2)
            let a = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            a.name = "state-\(state)"
            a.lifetime = .keepAlways
            add(a)
            app.terminate()
        }
    }
}
