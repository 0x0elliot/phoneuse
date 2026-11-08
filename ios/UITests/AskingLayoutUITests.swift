import XCTest

/// Shows each demo Live Activity state on the lock screen and attaches a screenshot, to check the layouts.
final class AskingLayoutUITests: XCTestCase {
    func testStateLayouts() throws {
        for state in ["idle", "delay", "asking", "driving", "paused"] {
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
