import SwiftUI

@main
struct PhoneUseApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel.shared
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .onOpenURL { model.pair(from: $0) }
                .onChange(of: phase, initial: true) { _, phase in
                    if phase == .active {
                        model.startPolling()
                        UIApplication.shared.registerForRemoteNotifications()  // iOS answers with the device token again
                        Task {
                            await PushRegistrar.shared.resendAll()
                            await model.syncActivity()
                            await model.checkNotifications()
                        }
                    } else {
                        model.stopPolling()
                    }
                }
        }
    }
}
