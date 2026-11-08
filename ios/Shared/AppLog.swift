import Foundation
import OSLog

/// A short log the owner (or a Mac with devicectl) can read: Library/Caches/phoneuse.log in the app's container,
/// also sent to the system log. Tokens appear only as their first 12 hex digits.
enum AppLog {
    private static let logger = Logger(subsystem: "co.lxe.phoneuse", category: "app")
    private static let queue = DispatchQueue(label: "co.lxe.phoneuse.log")
    private static let url = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("phoneuse.log")

    static func write(_ message: String) {
        logger.info("\(message, privacy: .public)")
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
        queue.async {
            if let size = try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int, size > 200_000 {
                try? FileManager.default.removeItem(at: url)
            }
            if let h = try? FileHandle(forWritingTo: url) {
                h.seekToEndOfFile()
                h.write(Data(line.utf8))
                try? h.close()
            } else {
                try? Data(line.utf8).write(to: url)
            }
        }
    }

    static func short(_ token: Data) -> String { String(CompanionCrypto.hex(token).prefix(12)) }
}
