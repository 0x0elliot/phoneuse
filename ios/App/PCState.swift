import Foundation

/// GET /v1/state (docs/COMPANION.md, "Endpoints").
struct PCState: Decodable, Equatable {
    struct PC: Decodable, Equatable { var id: String; var name: String; var version: String? }
    struct Bluetooth: Decodable, Equatable { var connected: Bool; var via: String? }
    struct Agent: Decodable, Equatable {
        var state: String
        var action: String?
        var since: Double?
        var steps: Int?
        /// "acting", "reading" or "thinking" while driving, if the PC sends it.
        var phase: String?
    }
    struct Audio: Decodable, Equatable {
        var on: Bool
        var needsRemirror: Bool?
        enum CodingKeys: String, CodingKey { case on, needsRemirror = "needs_remirror" }
    }
    struct Pending: Decodable, Equatable, Identifiable {
        var id: String
        var since: Double?
        var action: String?
        /// "countdown" or "ask".
        var mode: String?
        /// Countdown only: unix seconds when the PC starts the agent by itself.
        var deadline: Double?
    }
    /// Asking the owner before an agent session. Older PCs don't send it.
    /// When an agent starts: mode "auto" (go ahead), "countdown" (wait `seconds`, 5-30), or "ask".
    struct Session: Decodable, Equatable {
        var ask: Bool
        var mode: String?
        var seconds: Int?
        var pending: Pending?
        var currentMode: String { mode ?? (ask ? "ask" : "auto") }
    }
    struct Unlock: Decodable, Equatable {
        var passcodeSaved: Bool
        var pending: Pending?
        enum CodingKeys: String, CodingKey { case passcodeSaved = "passcode_saved", pending }
    }
    struct Bridge: Decodable, Equatable {
        var saved: Bool?
        var id: String?
        var ip: String?
        var ssid: String?
        var use: Bool
        var online: Bool
        var rttMs: Double?
        /// "good", "fair" or "weak", or nil when unknown: the bridge's Wi-Fi, and its link to the phone.
        var signal: Signal?
        var warning: Warning?
        enum CodingKeys: String, CodingKey { case saved, id, ip, ssid, use, online, signal, warning, rttMs = "rtt_ms" }
    }
    struct Signal: Decodable, Equatable { var wifi: String?; var phone: String? }
    struct Warning: Decodable, Equatable { var title: String; var detail: String? }

    var pc: PC
    var mirroring: Bool
    var phone: String?
    var bluetooth: Bluetooth
    var agent: Agent
    var awake: Bool
    var audio: Audio
    var session: Session?
    var unlock: Unlock
    var bridge: Bridge?
}

struct BridgeNetwork: Decodable, Identifiable, Hashable {
    var ssid: String
    var rssi: Int
    var secure: Bool
    var id: String { ssid }
}
