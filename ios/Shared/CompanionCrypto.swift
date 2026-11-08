import CryptoKit
import Foundation

/// Request signing and secret sealing, as docs/COMPANION.md ("Signing requests") describes them.
enum CompanionCrypto {
    static func hex(_ bytes: some Sequence<UInt8>) -> String {
        bytes.map { String(format: "%02x", $0) }.joined()
    }

    /// hex HMAC-SHA256 over METHOD\nPATH\nTIME\nNONCE\nSHA256HEX(BODY).
    static func signature(key: Data, method: String, path: String, time: String, nonce: String, body: Data) -> String {
        let bodyHash = hex(SHA256.hash(data: body))
        let message = [method, path, time, nonce, bodyHash].joined(separator: "\n")
        let mac = HMAC<SHA256>.authenticationCode(for: Data(message.utf8), using: SymmetricKey(data: key))
        return hex(mac)
    }

    static func sealKey(_ key: Data) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: key), salt: Data(),
                               info: Data("phoneuse seal".utf8), outputByteCount: 32)
    }

    /// base64 of nonce(12) | ciphertext | tag(16), AES-256-GCM with the field name as associated data.
    static func seal(key: Data, field: String, plaintext: String, nonce: AES.GCM.Nonce = AES.GCM.Nonce()) throws -> String {
        let box = try AES.GCM.seal(Data(plaintext.utf8), using: sealKey(key), nonce: nonce,
                                   authenticating: Data(field.utf8))
        return box.combined!.base64EncodedString()
    }

    static func randomNonceHex() -> String {
        var bytes = [UInt8](repeating: 0, count: 16)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return hex(bytes)
    }

    static func base64urlDecode(_ s: String) -> Data? {
        var b = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        b += String(repeating: "=", count: (4 - b.count % 4) % 4)
        return Data(base64Encoded: b)
    }
}
