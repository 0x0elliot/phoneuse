import CryptoKit
import XCTest
@testable import PhoneUse

/// The expected values come from the Python mock: `python3 ios/mock/vectors.py`.
final class CompanionCryptoTests: XCTestCase {
    let key = Data(0..<32)

    func testPairingLinkKey() {
        XCTAssertEqual(CompanionCrypto.base64urlDecode("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"), key)
    }

    func testSignatureGET() {
        XCTAssertEqual(
            CompanionCrypto.signature(key: key, method: "GET", path: "/v1/state", time: "1794153854",
                                      nonce: "00112233445566778899aabbccddeeff", body: Data()),
            "1c5762d8b0f64f1e1c0ef1ea0a0039b8c986e67f3ebd76df8350a1bcf47030e0")
    }

    func testSignaturePOSTWithQuery() {
        XCTAssertEqual(
            CompanionCrypto.signature(key: key, method: "POST", path: "/v1/awake?x=1", time: "1794153854",
                                      nonce: "ffeeddccbbaa99887766554433221100", body: Data(#"{"on":true}"#.utf8)),
            "af37947d3ae8825736a7cd9675820467e2db228d41151c7262588bd7a00293e9")
    }

    func testSealKey() {
        let derived = CompanionCrypto.sealKey(key).withUnsafeBytes { Data($0) }
        XCTAssertEqual(CompanionCrypto.hex(derived), "150d8210fe83f04221b850ee44a6a521aa72af3da8db0e16a799f33b34d763a3")
    }

    func testSeal() throws {
        let sealed = try CompanionCrypto.seal(key: key, field: "passcode", plaintext: "123456",
                                              nonce: AES.GCM.Nonce(data: Data(0..<12)))
        XCTAssertEqual(sealed, "AAECAwQFBgcICQoLX/89WX3IlbbfOoaZZimA1k+5z/Y+6w==")
    }

    func testSealUsesFieldAsAssociatedData() throws {
        let sealed = try CompanionCrypto.seal(key: key, field: "password", plaintext: "123456",
                                              nonce: AES.GCM.Nonce(data: Data(0..<12)))
        XCTAssertNotEqual(sealed, "AAECAwQFBgcICQoLX/89WX3IlbbfOoaZZimA1k+5z/Y+6w==")
    }

    func testPairingLink() throws {
        let url = URL(string: "phoneuse://pair?id=a1b2c3d4e5f60718&name=lxe%20desktop&host=192.168.0.10&port=8778&key=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8")!
        let p = try XCTUnwrap(Pairing(url: url))
        XCTAssertEqual(p, Pairing(id: "a1b2c3d4e5f60718", name: "lxe desktop", host: "192.168.0.10", port: 8778, key: key))
        XCTAssertNil(Pairing(url: URL(string: "phoneuse://pair?id=x&host=h&key=short")!))
    }

    func testContentStateDecodesPushPayload() throws {
        let json = #"{"state": "driving", "action": "Opening Gmail", "steps": 12, "startedAt": 1794153854}"#
        let s = try JSONDecoder().decode(AgentActivityAttributes.ContentState.self, from: Data(json.utf8))
        XCTAssertEqual(s.steps, 12)
        XCTAssertEqual(s.startDate, Date(timeIntervalSince1970: 1794153854))
        XCTAssertNil(s.phase)
    }

    func testContentStatePhase() throws {
        let json = #"{"state": "driving", "phase": "reading", "action": "Opening Gmail", "steps": 12, "startedAt": 1794153854}"#
        var s = try JSONDecoder().decode(AgentActivityAttributes.ContentState.self, from: Data(json.utf8))
        XCTAssertEqual(s.currentPhase, "reading")
        s.state = "paused"
        XCTAssertEqual(s.currentPhase, "paused")
    }

    func testStateDecodesSession() throws {
        let json = #"""
        {"pc": {"id": "x", "name": "pc"}, "mirroring": true, "bluetooth": {"connected": true},
         "agent": {"state": "idle"}, "awake": true, "audio": {"on": true},
         "session": {"ask": true, "pending": {"id": "s9", "since": 1794153854, "action": "Opening Gmail"}},
         "unlock": {"passcode_saved": false, "pending": null}, "bridge": null}
        """#
        let s = try JSONDecoder().decode(PCState.self, from: Data(json.utf8))
        XCTAssertEqual(s.session?.ask, true)
        XCTAssertEqual(s.session?.pending?.id, "s9")
        XCTAssertEqual(s.session?.pending?.action, "Opening Gmail")
    }

    func testStateDecodes() throws {
        let json = #"""
        {"pc": {"id": "ba471d734209b2fd", "name": "archlinux", "version": "3902b41"}, "mirroring": false,
         "phone": "LXEPhone17Pro", "bluetooth": {"connected": false, "via": "bridge"},
         "agent": {"state": "idle", "action": "", "since": null, "steps": 0}, "awake": true,
         "audio": {"on": true, "needs_remirror": false}, "unlock": {"passcode_saved": true, "pending": null},
         "bridge": {"saved": true, "id": "4cebd64377b8", "ip": "192.168.0.51", "ssid": "giraffe-iot", "use": true,
                    "online": true, "rtt_ms": null}}
        """#
        let s = try JSONDecoder().decode(PCState.self, from: Data(json.utf8))
        XCTAssertEqual(s.bridge?.ssid, "giraffe-iot")
        XCTAssertTrue(s.unlock.passcodeSaved)
    }
}
