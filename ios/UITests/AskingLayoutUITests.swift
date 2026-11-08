import XCTest

/// Shows the demo asking Live Activity on the lock screen and attaches a screenshot, to check its layout.
final class AskingLayoutUITests: XCTestCase {
    func testAskingLayout() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-PUDemoAsking"]
        app.launch()
        sleep(2)
        XCUIDevice.shared.press(.home)
        sleep(1)
        XCUIDevice.shared.perform(NSSelectorFromString("pressLockButton"))
        sleep(2)
        let a = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        a.name = "asking-lock"
        a.lifetime = .keepAlways
        add(a)
    }
}
