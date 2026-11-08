import Foundation
import Security

let appGroup = "group.co.lxe.phoneuse"

/// The PC the app is paired with. The key lives in the Keychain, shared with the widget extension through the
/// app group; the rest lives in the app group's defaults.
struct Pairing: Equatable {
    var id: String
    var name: String
    var host: String
    var port: Int
    var key: Data

    /// Parses phoneuse://pair?id=…&name=…&host=…&port=8778&key=…
    init?(url: URL) {
        guard url.scheme == "phoneuse", url.host == "pair",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems else { return nil }
        func value(_ name: String) -> String? { items.first { $0.name == name }?.value }
        guard let id = value("id"), let host = value("host"), let keyText = value("key"),
              let key = CompanionCrypto.base64urlDecode(keyText), key.count == 32 else { return nil }
        self.init(id: id, name: value("name") ?? id, host: host, port: Int(value("port") ?? "") ?? 8778, key: key)
    }

    init(id: String, name: String, host: String, port: Int, key: Data) {
        self.id = id
        self.name = name
        self.host = host
        self.port = port
        self.key = key
    }
}

/// Whether the build has the app group entitlement. Builds without it keep everything in the app's own storage;
/// the Live Activity's intents still work, because a LiveActivityIntent runs in the app's process.
let appGroupAvailable = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup) != nil

enum PairingStore {
    static let defaults: UserDefaults = {
        guard appGroupAvailable, let group = UserDefaults(suiteName: appGroup) else { return .standard }
        // A build that gains the app group moves the pairing over from the app's own defaults.
        if group.string(forKey: "pc.id") == nil, UserDefaults.standard.string(forKey: "pc.id") != nil {
            for k in ["pc.id", "pc.name", "pc.host", "pc.port", "pointer.on"] {
                group.set(UserDefaults.standard.object(forKey: k), forKey: k)
            }
        }
        return group
    }()
    private static let service = "co.lxe.phoneuse.pairing"

    static func load() -> Pairing? {
        guard let id = defaults.string(forKey: "pc.id"), let host = defaults.string(forKey: "pc.host"),
              let key = Keychain.read(service: service, account: id) else { return nil }
        return Pairing(id: id, name: defaults.string(forKey: "pc.name") ?? id, host: host,
                       port: defaults.integer(forKey: "pc.port"), key: key)
    }

    static func save(_ p: Pairing) {
        if let old = defaults.string(forKey: "pc.id"), old != p.id { Keychain.delete(service: service, account: old) }
        Keychain.write(p.key, service: service, account: p.id)
        defaults.set(p.id, forKey: "pc.id")
        defaults.set(p.name, forKey: "pc.name")
        defaults.set(p.host, forKey: "pc.host")
        defaults.set(p.port, forKey: "pc.port")
    }

    static func updateAddress(host: String, port: Int) {
        defaults.set(host, forKey: "pc.host")
        defaults.set(port, forKey: "pc.port")
    }

    static func forget() {
        if let id = defaults.string(forKey: "pc.id") { Keychain.delete(service: service, account: id) }
        for k in ["pc.id", "pc.name", "pc.host", "pc.port"] { defaults.removeObject(forKey: k) }
    }
}

/// Generic-password items in the app group's keychain access group when the build has the group, and in the
/// app's own keychain otherwise. Reads look in both.
enum Keychain {
    private static func query(_ service: String, _ account: String, group: Bool) -> [String: Any] {
        var q: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                kSecAttrService as String: service, kSecAttrAccount as String: account]
        if group { q[kSecAttrAccessGroup as String] = appGroup }
        return q
    }

    static func read(service: String, account: String) -> Data? {
        for group in [true, false] {
            var q = query(service, account, group: group)
            q[kSecReturnData as String] = true
            var out: AnyObject?
            if SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data { return data }
        }
        return nil
    }

    static func write(_ data: Data, service: String, account: String) {
        delete(service: service, account: account)
        for group in [appGroupAvailable, false] {
            var q = query(service, account, group: group)
            q[kSecValueData as String] = data
            q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            if SecItemAdd(q as CFDictionary, nil) == errSecSuccess { return }
        }
    }

    static func delete(service: String, account: String) {
        for group in [true, false] { SecItemDelete(query(service, account, group: group) as CFDictionary) }
    }
}
