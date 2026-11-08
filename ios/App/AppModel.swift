import ActivityKit
import Foundation
import OSLog
import UIKit
import UserNotifications
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
    /// Notifications are off (not yet allowed, or denied) for PhoneUse.
    @Published var notificationsOff = false
    /// Whether Phone Use is in front; set from the scene phase.
    @Published var foreground = false
    /// The session request to show as a sheet: pending, and the app in front.
    var foregroundRequest: PCState.Pending? { foreground ? state?.session?.pending : nil }
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
            await PushRegistrar.shared.resendAll()
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
            if s != state {
                state = s
                await reconcileActivities(s)
            }
            reachable = true
            await RequestNotifications.prune(session: s.session?.pending?.id, unlock: s.unlock.pending?.id)
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

    func setSessionMode(_ mode: String) async { await run("sessionMode", "POST", "/v1/session/ask", ["mode": mode]) }

    func setSessionSeconds(_ seconds: Int) async {
        await run("sessionMode", "POST", "/v1/session/ask", ["seconds": seconds])
    }

    func answerSession(id: String, approve: Bool) async {
        await run("session", "POST", "/v1/session/answer", ["id": id, "approve": approve])
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

    private static func live() -> [Activity<AgentActivityAttributes>] {
        Activity<AgentActivityAttributes>.activities.filter { $0.activityState == .active || $0.activityState == .stale }
    }

    /// Only one activity may exist: the PC updates one token, and a second would hide it. Ends every other.
    func keepOnly(_ id: String) async {
        for a in Self.live() where a.id != id {
            AppLog.write("ending extra activity \(a.id), keeping \(id)")
            await a.end(nil, dismissalPolicy: .immediate)
        }
    }

    /// The activity stays up while the phone mirrors to the PC, showing idle, asking, driving or paused. When the
    /// app becomes active: with no mirroring, it ends any activity; with mirroring, it keeps exactly one, the one whose
    /// token the PC has if there are several, and starts one in the PC's current state if there is none (the app was
    /// ended, or iOS removed it).
    func checkNotifications() async {
        let status = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
        notificationsOff = !(status == .authorized || status == .provisional || status == .ephemeral)
    }

    /// Asks for notifications, or opens PhoneUse's notification settings if the owner already said no.
    func turnOnNotifications() async {
        let status = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
        if status == .notDetermined {
            _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
            UIApplication.shared.registerForRemoteNotifications()
        } else if let url = URL(string: UIApplication.openNotificationSettingsURLString) {
            await UIApplication.shared.open(url)
        }
        await checkNotifications()
    }

    func syncActivity() async {
        await refresh()
        guard reachable, let s = state else { return }
        let live = Self.live()
        for a in live { AppLog.write("activity \(a.id) \(a.activityState) shows \(a.content.state.state)/\(a.content.state.phase ?? "-")") }
        guard s.mirroring else {
            for a in live {
                AppLog.write("not mirroring; ending activity \(a.id)")
                await a.end(nil, dismissalPolicy: .immediate)
            }
            return
        }
        if live.count > 1 {
            let known = await PushRegistrar.shared.lastActivityId
            await keepOnly((live.first { $0.id == known } ?? live.last!).id)
        }
        guard live.isEmpty else { return }
        do {
            let a = try Activity.request(attributes: AgentActivityAttributes(pcName: s.pc.name),
                                         content: ActivityContent(state: Self.contentState(s), staleDate: nil),
                                         pushType: .token)
            AppLog.write("started activity \(a.id) (\(a.content.state.state))")
        } catch {
            AppLog.write("starting the activity failed: \(error)")
        }
    }

    /// While the app is open, corrects an activity whose state differs from the PC's, in case iOS dropped a push.
    private func reconcileActivities(_ s: PCState) async {
        let want = Self.contentState(s)
        for a in Self.live() {
            let have = a.content.state
            guard have.state != want.state || (want.asking && have.requestId != want.requestId) else { continue }
            var next = want
            if want.state == "driving" { next.phase = (have.state == "driving" ? have.phase : nil) ?? "thinking" }
            AppLog.write("activity \(a.id) showed \(have.state), the PC says \(want.state); updating")
            await a.update(ActivityContent(state: next, staleDate: nil))
        }
    }

    #if DEBUG
    /// Launched with -PUDemoActivity (simulator checks): a driving activity with no PC, to watch its animation.
    func startDemoActivityIfAsked() {
        let args = ProcessInfo.processInfo.arguments
        guard args.contains("-PUDemoActivity") || args.contains("-PUDemoAsking") else { return }
        let now = Date().timeIntervalSince1970
        var state = AgentActivityAttributes.ContentState(state: "driving", phase: "thinking", requestId: nil,
                                                         action: "Opening Settings", steps: 3, startedAt: now - 5,
                                                         updatedAt: now)
        if args.contains("-PUDemoAsking") {
            state = .init(state: "asking", phase: "asking", requestId: "demo", action: "Pressing escape", steps: 0,
                          startedAt: now, updatedAt: now)
            state.deadline = now + 30
        }
        _ = try? Activity.request(attributes: AgentActivityAttributes(pcName: "demo"),
                                  content: ActivityContent(state: state, staleDate: nil), pushType: nil)
    }
    #endif

    static func contentState(_ s: PCState) -> AgentActivityAttributes.ContentState {
        let now = Date().timeIntervalSince1970
        if let p = s.session?.pending {
            var c = AgentActivityAttributes.ContentState(state: "asking", phase: "asking", requestId: p.id,
                                                         action: p.action ?? "", steps: 0, startedAt: p.since ?? now,
                                                         updatedAt: now)
            c.deadline = p.deadline
            return c
        }
        switch s.agent.state {
        case "driving", "paused":
            return .init(state: s.agent.state, phase: s.agent.state == "paused" ? "paused" : "thinking", requestId: nil,
                         action: s.agent.action ?? "", steps: s.agent.steps ?? 0, startedAt: s.agent.since ?? now,
                         updatedAt: now)
        default:
            return .init(state: "idle", phase: nil, requestId: nil, action: "", steps: 0, startedAt: now, updatedAt: now)
        }
    }

}
