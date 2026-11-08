import ActivityKit
import Foundation
import OSLog
import UIKit
import UserNotifications

/// Collects the APNs device token, the Live Activity push-to-start token and each activity's push token, and
/// sends them to the PC with POST /v1/push (docs/COMPANION.md, "Push").
///
/// iOS launches the app in the background when the PC's push-to-start creates an activity, and suspends it soon
/// after, so each send runs in a background task. A send that fails anyway is logged and retried when the app
/// next becomes active, which also re-sends every current token.
actor PushRegistrar {
    static let shared = PushRegistrar()

    #if DEBUG
    static let env = "sandbox"
    #else
    static let env = "production"
    #endif

    private let log = Logger(subsystem: "co.lxe.phoneuse", category: "push")
    private var device: String?
    private var pushToStart: String?
    private var watched: Set<String> = []
    private var started = false

    private var base: [String: Any] {
        ["bundle_id": Bundle.main.bundleIdentifier ?? "co.lxe.phoneuse", "env": Self.env]
    }

    func setDevice(_ token: Data) async {
        device = CompanionCrypto.hex(token)
        await send(["device": device!], what: "device token")
    }

    /// Re-sends every token, with "env": at launch, after pairing, and whenever the app becomes active. A PC that
    /// last heard from another build (TestFlight is production, a development build is sandbox) gets this
    /// build's tokens and environment.
    func resendAll() async {
        startWatching()
        if let data = Activity<AgentActivityAttributes>.pushToStartToken { pushToStart = CompanionCrypto.hex(data) }
        var body: [String: Any] = [:]
        if let device { body["device"] = device }
        if let pushToStart { body["push_to_start"] = pushToStart }
        if !body.isEmpty { await send(body, what: "device and push-to-start tokens") }
        for activity in Activity<AgentActivityAttributes>.activities {
            watch(activity)
            if let token = activity.pushToken { await sendActivity(activity.id, token) }
        }
    }

    /// Starts once, at launch (including background launches for push-to-start).
    func startWatching() {
        guard !started else { return }
        started = true
        Task {
            for await data in Activity<AgentActivityAttributes>.pushToStartTokenUpdates {
                pushToStart = CompanionCrypto.hex(data)
                await send(["push_to_start": pushToStart!], what: "push-to-start token")
            }
        }
        for activity in Activity<AgentActivityAttributes>.activities { watch(activity) }
        Task {
            for await activity in Activity<AgentActivityAttributes>.activityUpdates { watch(activity) }
        }
    }

    private func watch(_ activity: Activity<AgentActivityAttributes>) {
        guard watched.insert(activity.id).inserted else { return }
        log.info("watching activity \(activity.id, privacy: .public)")
        if let token = activity.pushToken { Task { await sendActivity(activity.id, token) } }
        Task {
            for await data in activity.pushTokenUpdates { await sendActivity(activity.id, data) }
        }
    }

    private func sendActivity(_ id: String, _ token: Data) async {
        await send(["activity": ["id": id, "token": CompanionCrypto.hex(token)]], what: "activity \(id) token")
    }

    private func send(_ fields: [String: Any], what: String) async {
        let client: CompanionClient
        do { client = try CompanionClient.paired() } catch {
            log.info("not paired; \(what, privacy: .public) not sent")
            return
        }
        var body = base
        body.merge(fields) { $1 }
        let task = await BackgroundTask.begin("push tokens")
        defer { Task { await BackgroundTask.end(task) } }
        do {
            _ = try await client.send("POST", "/v1/push", json: body, timeout: 10)
            log.info("sent \(what, privacy: .public)")
        } catch {
            log.error("sending \(what, privacy: .public) failed: \(String(describing: error), privacy: .public)")
        }
    }
}

/// Asks iOS for time to finish a request when the app is in the background.
@MainActor
enum BackgroundTask {
    private static var open: Set<UIBackgroundTaskIdentifier> = []

    static func begin(_ name: String) -> UIBackgroundTaskIdentifier {
        let id = UIApplication.shared.beginBackgroundTask(withName: name) {
            // iOS calls this on the main thread when the time runs out.
            MainActor.assumeIsolated { for id in open { end(id) } }
        }
        if id != .invalid { open.insert(id) }
        return id
    }

    static func end(_ id: UIBackgroundTaskIdentifier) {
        guard open.remove(id) != nil else { return }
        UIApplication.shared.endBackgroundTask(id)
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        let unlock = UNNotificationAction(identifier: "UNLOCK", title: "Unlock", options: [.authenticationRequired])
        let deny = UNNotificationAction(identifier: "DENY", title: "Deny", options: [.destructive])
        let allow = UNNotificationAction(identifier: "ALLOW", title: "Allow", options: [])
        let denySession = UNNotificationAction(identifier: "DENY", title: "Deny", options: [.destructive])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: "UNLOCK", actions: [unlock, deny], intentIdentifiers: []),
            UNNotificationCategory(identifier: "SESSION", actions: [allow, denySession], intentIdentifiers: []),
        ])
        center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
        application.registerForRemoteNotifications()
        Task { await PushRegistrar.shared.resendAll() }  // also on background launches
        return true
    }

    /// The PC's background push when a request ends without the app answering it:
    /// {"aps": {"content-available": 1}, "request_over": {"kind": "session" | "unlock", "id": "…"}}
    func application(_ application: UIApplication, didReceiveRemoteNotification userInfo: [AnyHashable: Any])
        async -> UIBackgroundFetchResult {
        guard let over = userInfo["request_over"] as? [String: Any], let kind = over["kind"] as? String,
              let id = over["id"] as? String else { return .noData }
        await RequestNotifications.remove(kind: kind, id: id)
        await AppModel.shared.refresh()
        return .newData
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { await PushRegistrar.shared.setDevice(deviceToken) }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Logger(subsystem: "co.lxe.phoneuse", category: "push").error("APNs registration failed: \(String(describing: error), privacy: .public)")
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification)
        async -> UNNotificationPresentationOptions {
        let info = notification.request.content.userInfo
        if info["session_id"] != nil || info["unlock_id"] != nil { Task { await AppModel.shared.refresh() } }
        return [.banner, .list, .sound]
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let info = response.notification.request.content.userInfo
        let approve: Bool
        switch response.actionIdentifier {
        case "UNLOCK", "ALLOW": approve = true
        case "DENY": approve = false
        default: return  // Tapping the notification opens the app, which shows the request.
        }
        let path: String, id: String
        if let unlock = info["unlock_id"] as? String {
            (path, id) = ("/v1/unlock/answer", unlock)
        } else if let session = info["session_id"] as? String {
            (path, id) = ("/v1/session/answer", session)
        } else {
            return
        }
        let task = BackgroundTask.begin("answer")
        do {
            _ = try await CompanionClient.paired().send("POST", path, json: ["id": id, "approve": approve])
        } catch {
            Logger(subsystem: "co.lxe.phoneuse", category: "push")
                .error("\(path, privacy: .public) failed: \(String(describing: error), privacy: .public)")
        }
        BackgroundTask.end(task)
        await AppModel.shared.refresh()
    }
}

/// The delivered SESSION and UNLOCK notifications, kept in step with the PC's pending requests.
enum RequestNotifications {
    private static let keys = ["session": "session_id", "unlock": "unlock_id"]

    /// Removes the notifications for one request that has ended.
    static func remove(kind: String, id: String) async {
        guard let key = keys[kind] else { return }
        await removeWhere { ($0[key] as? String) == id }
    }

    /// Removes the notifications for requests that are no longer pending.
    static func prune(session: String?, unlock: String?) async {
        await removeWhere { info in
            if let id = info["session_id"] as? String { return id != session }
            if let id = info["unlock_id"] as? String { return id != unlock }
            return false
        }
    }

    private static func removeWhere(_ match: @escaping ([AnyHashable: Any]) -> Bool) async {
        let center = UNUserNotificationCenter.current()
        let ids = await center.deliveredNotifications()
            .filter { match($0.request.content.userInfo) }
            .map(\.request.identifier)
        if !ids.isEmpty { center.removeDeliveredNotifications(withIdentifiers: ids) }
    }
}
