import XCTest

/// Drives every setting against the mock server. Start it first, with the fixed test key:
///     python3 ios/mock/mock_server.py --key AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8 --cursor-delay 1
final class SettingsUITests: XCTestCase {
    let link = "phoneuse://pair?id=a1b2c3d4e5f60718&name=mock-pc&host=127.0.0.1&port=8778&key=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    let app = XCUIApplication()

    override func setUp() { continueAfterFailure = false }

    func flip(_ id: String) {
        let s = app.switches[id]
        XCTAssertTrue(s.waitForExistence(timeout: 5))
        s.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap()
    }

    func value(_ id: String) -> String { app.switches[id].value as? String ?? "" }

    func waitFor(_ predicate: String, _ element: XCUIElement, timeout: TimeInterval = 6) {
        let e = expectation(for: NSPredicate(format: predicate), evaluatedWith: element)
        wait(for: [e], timeout: timeout)
    }

    func screenshot(_ name: String) {
        let a = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    func testEverySetting() throws {
        try XCTSkipIf(ProcessInfo.processInfo.environment["PU_LINK"] != nil, "This run is against a real PC.")
        app.launch()
        // Pair from the link, the way Safari or the Camera would open it.
        XCUIDevice.shared.system.open(URL(string: link)!)
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let open = springboard.buttons["Open"]
        if open.waitForExistence(timeout: 3) { open.tap() }
        XCTAssertTrue(app.staticTexts["mock-pc"].waitForExistence(timeout: 10))
        screenshot("paired")

        // Agent: take over, then resume.
        app.buttons["takeover"].tap()
        XCTAssertTrue(app.buttons["resume"].waitForExistence(timeout: 6))
        app.buttons["resume"].tap()
        XCTAssertTrue(app.buttons["takeover"].waitForExistence(timeout: 6))

        // Ask before an agent session, and allow the pending request.
        app.buttons["sessionMode"].tap()
        app.buttons["Ask every time"].tap()
        XCTAssertTrue(app.staticTexts["sessionRequest"].exists || app.otherElements["sessionRequest"].exists
                      || app.buttons["allowSession"].exists)
        app.buttons["allowSession"].tap()
        waitFor("exists == false", app.buttons["allowSession"])

        // A pending unlock request: approve it.
        app.buttons["approveUnlock"].tap()
        waitFor("exists == false", app.buttons["approveUnlock"])

        // Passcode: save, then forget.
        app.buttons["savePasscode"].tap()
        let field = app.secureTextFields["passcodeField"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText("123456")
        app.buttons["passcodeSave"].tap()
        XCTAssertTrue(app.buttons["forgetPasscode"].waitForExistence(timeout: 6))
        app.buttons["forgetPasscode"].tap()
        app.buttons["Forget"].tap()
        waitFor("exists == false", app.buttons["forgetPasscode"])

        // Keep awake.
        let awake = value("awake")
        flip("awake")
        waitFor("value != %@".replacingOccurrences(of: "%@", with: "'\(awake)'"), app.switches["awake"])

        // Keyboard and pointer.
        app.buttons["keyboard"].tap()
        app.swipeUp()
        app.buttons["On"].tap()
        sleep(2)
        app.buttons["Off"].tap()
        sleep(2)
        XCTAssertFalse(app.staticTexts["error"].exists)

        // Bridge: input through it, then move it to another network.
        let use = value("bridgeUse")
        flip("bridgeUse")
        waitFor("value != '\(use)'", app.switches["bridgeUse"])
        flip("bridgeUse")
        waitFor("value == '\(use)'", app.switches["bridgeUse"])
        app.buttons["bridgeNetwork"].tap()
        let net = app.buttons["network-Giraffe"]
        XCTAssertTrue(net.waitForExistence(timeout: 6))
        screenshot("networks")
        net.tap()
        let pw = app.secureTextFields.firstMatch
        XCTAssertTrue(pw.waitForExistence(timeout: 5))
        pw.typeText("hunter22")
        app.buttons["Join"].tap()
        XCTAssertTrue(app.staticTexts["Giraffe"].waitForExistence(timeout: 8))

        // Mirror audio: the PC restarts the mirror, so the app asks to mirror again.
        app.swipeUp()
        flip("audio")
        XCTAssertTrue(app.alerts["Mirror again"].waitForExistence(timeout: 6))
        screenshot("remirror")
        app.alerts["Mirror again"].buttons["OK"].tap()
        screenshot("settings")

        // The Live Activity runs while the PC mirrors; the PC drives it with pushes.
    }
}
