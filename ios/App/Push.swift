import ActivityKit
import Foundation
import UIKit
import UserNotifications

/// Collects the APNs device token, the Live Activity push-to-start token and each activity's push token, and
/// sends them to the PC with POST /v1/push (docs/COMPANION.md, "Push").
actor PushRegistrar {
    static let shared = PushRegistrar()

    #if DEBUG
    static let env = "sandbox"
    #else
    static let env = "production"
    #endif

    private var tokens: [String: Any] = [:]
    private var watched: Set<String> = []

    func set(_ field: String, _ value: Any) async {
        tokens[field] = value
        await send(["bundle_id": Bundle.main.bundleIdentifier ?? "co.lxe.phoneuse", "env": Self.env, field: value])
    }

    /// After pairing, the new PC gets every token the app has.
    func pairingChanged() async {
        guard !tokens.isEmpty else { return }
        var body: [String: Any] = ["bundle_id": Bundle.main.bundleIdentifier ?? "co.lxe.phoneuse", "env": Self.env]
        body.merge(tokens) { $1 }
        await send(body)
    }

    private func send(_ body: [String: Any]) async {
        guard let client = try? CompanionClient.paired() else { return }
        _ = try? await client.send("POST", "/v1/push", json: body)
    }

    func startWatching() {
        Task {
            for await data in Activity<AgentActivityAttributes>.pushToStartTokenUpdates {
                await set("push_to_start", CompanionCrypto.hex(data))
            }
        }
        Task {
            for activity in Activity<AgentActivityAttributes>.activities { watch(activity) }
            for await activity in Activity<AgentActivityAttributes>.activityUpdates { watch(activity) }
        }
    }

    private func watch(_ activity: Activity<AgentActivityAttributes>) {
        guard watched.insert(activity.id).inserted else { return }
        Task {
            for await data in activity.pushTokenUpdates {
                await set("activity", ["id": activity.id, "token": CompanionCrypto.hex(data)])
            }
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        let unlock = UNNotificationAction(identifier: "UNLOCK", title: "Unlock", options: [.authenticationRequired])
        let deny = UNNotificationAction(identifier: "DENY", title: "Deny", options: [.destructive])
        center.setNotificationCategories([UNNotificationCategory(identifier: "UNLOCK", actions: [unlock, deny],
                                                                 intentIdentifiers: [])])
        center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
        application.registerForRemoteNotifications()
        Task { await PushRegistrar.shared.startWatching() }
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { await PushRegistrar.shared.set("device", CompanionCrypto.hex(deviceToken)) }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {}

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification)
        async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let info = response.notification.request.content.userInfo
        guard let id = info["unlock_id"] as? String else { return }
        let approve: Bool
        switch response.actionIdentifier {
        case "UNLOCK": approve = true
        case "DENY": approve = false
        default: return  // Tapping the notification opens the app, which shows the request.
        }
        _ = try? await CompanionClient.paired().send("POST", "/v1/unlock/answer", json: ["id": id, "approve": approve])
        await AppModel.shared.refresh()
    }
}
