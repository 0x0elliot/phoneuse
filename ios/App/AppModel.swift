import ActivityKit
import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    @Published var pairing: Pairing? = PairingStore.load()
    @Published var state: PCState?
    @Published var reachable = false
    @Published var error: String?
    @Published var busy: Set<String> = []
    @Published var askRemirror = false
    /// The last pointer setting the app sent; the state doesn't report it.
    @Published var pointerOn: Bool? = PairingStore.defaults.object(forKey: "pointer.on") as? Bool

    private var polling: Task<Void, Never>?

    var client: CompanionClient? { pairing.map(CompanionClient.init) }

    func pair(from url: URL) {
        guard let p = Pairing(url: url) else {
            error = "That pairing link isn't valid."
            return
        }
        PairingStore.save(p)
        pairing = p
        state = nil
        error = nil
        Task {
            await refresh()
            await PushRegistrar.shared.pairingChanged()
        }
    }

    func unpair() {
        PairingStore.forget()
        pairing = nil
        state = nil
        reachable = false
    }

    func startPolling() {
        polling?.cancel()
        polling = Task {
            while !Task.isCancelled {
                await refresh()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    func stopPolling() {
        polling?.cancel()
        polling = nil
    }

    func refresh() async {
        guard let client else { return }
        do {
            let s = try await client.get("/v1/state", as: PCState.self)
            if s != state { state = s }
            reachable = true
            if let p = PairingStore.load(), p != pairing { pairing = p }
        } catch CompanionError.server(let status, let message) where status == 401 {
            reachable = false
            error = message
        } catch {
            reachable = false
        }
    }

    /// Sends one setting and refreshes the state. `key` names the control, which shows a spinner meanwhile.
    @discardableResult
    func run(_ key: String, _ method: String, _ path: String, _ json: [String: Any]? = nil,
             timeout: TimeInterval = 6) async -> Data? {
        guard let client else { return nil }
        busy.insert(key)
        defer { busy.remove(key) }
        do {
            let data = try await client.send(method, path, json: json, timeout: timeout)
            error = nil
            await refresh()
            return data
        } catch {
            self.error = error.localizedDescription
            await refresh()
            return nil
        }
    }

    func takeOver() async {
        if await run("agent", "POST", "/v1/agent/takeover", [:]) != nil { await setActivitiesState("paused") }
    }

    func resume() async {
        if await run("agent", "POST", "/v1/agent/resume", [:]) != nil { await setActivitiesState("driving") }
    }

    func answerUnlock(id: String, approve: Bool) async {
        await run("unlock", "POST", "/v1/unlock/answer", ["id": id, "approve": approve])
    }

    func savePasscode(_ passcode: String) async {
        guard let key = pairing?.key, let sealed = try? CompanionCrypto.seal(key: key, field: "passcode", plaintext: passcode)
        else { return }
        await run("passcode", "POST", "/v1/passcode", ["sealed": sealed])
    }

    func forgetPasscode() async { await run("passcode", "DELETE", "/v1/passcode") }

    func setAwake(_ on: Bool) async { await run("awake", "POST", "/v1/awake", ["on": on]) }

    func toggleKeyboard() async { await run("keyboard", "POST", "/v1/keyboard", [:]) }

    func setPointer(_ on: Bool) async {
        if await run("pointer", "POST", "/v1/cursor", ["on": on], timeout: 25) != nil {
            pointerOn = on
            PairingStore.defaults.set(on, forKey: "pointer.on")
        }
    }

    func setBridge(_ on: Bool) async { await run("bridge", "POST", "/v1/bridge/use", ["on": on]) }

    func networks() async throws -> [BridgeNetwork] {
        guard let client else { throw CompanionError.notPaired }
        struct Answer: Decodable { var networks: [BridgeNetwork] }
        return try await client.get("/v1/bridge/networks", as: Answer.self).networks
            .sorted { $0.rssi > $1.rssi }
    }

    func moveBridge(ssid: String, password: String?) async -> Bool {
        var body: [String: Any] = ["ssid": ssid]
        if let password, let key = pairing?.key {
            body["sealed"] = try? CompanionCrypto.seal(key: key, field: "password", plaintext: password)
        }
        return await run("network", "POST", "/v1/bridge/network", body, timeout: 30) != nil
    }

    func setAudio(_ on: Bool) async {
        guard let data = await run("audio", "POST", "/v1/mirror/audio", ["on": on], timeout: 20) else { return }
        let answer = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        if answer?["needs_remirror"] as? Bool == true { askRemirror = true }
    }

    // MARK: Live Activity preview

    func startTestActivity() {
        let state = AgentActivityAttributes.ContentState(
            state: "driving", action: "Opening Gmail", steps: 12, startedAt: Date().timeIntervalSince1970 - 95)
        do {
            _ = try Activity.request(attributes: AgentActivityAttributes(pcName: pairing?.name ?? "PC"),
                                     content: ActivityContent(state: state, staleDate: nil), pushType: .token)
        } catch {
            self.error = "The Live Activity didn't start: \(error.localizedDescription)"
        }
    }

    func endActivities() async {
        for a in Activity<AgentActivityAttributes>.activities { await a.end(nil, dismissalPolicy: .immediate) }
    }
}
