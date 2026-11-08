import XCTest

/// Pairs with a real PC and shows its state, without changing any setting. Skipped unless the runner gets a link:
///     TEST_RUNNER_PU_LINK='phoneuse://pair?…' xcodebuild test -only-testing:PhoneUseUITests/RealPCUITests …
final class RealPCUITests: XCTestCase {
    func testPairAndShowState() throws {
        let env = ProcessInfo.processInfo.environment
        let link = try XCTUnwrap(env["PU_LINK"].flatMap(URL.init(string:)), "PU_LINK isn't set")
        let name = try XCTUnwrap(URLComponents(url: link, resolvingAgainstBaseURL: false)?
            .queryItems?.first { $0.name == "name" }?.value)
        let app = XCUIApplication()
        app.launch()
        XCUIDevice.shared.system.open(link)
        let open = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Open"]
        if open.waitForExistence(timeout: 3) { open.tap() }
        XCTAssertTrue(app.staticTexts[name].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["passcodeStatus"].exists || app.otherElements["passcodeStatus"].exists
                      || app.cells.count > 0)
        XCTAssertFalse(app.staticTexts["offline"].exists)
        sleep(3)
        for (i, _) in [0, 1].enumerated() {
            let a = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            a.name = "real-\(i)"
            a.lifetime = .keepAlways
            add(a)
            app.swipeUp()
        }
    }
}
