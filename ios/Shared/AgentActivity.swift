import ActivityKit
import AppIntents
import Foundation

/// The Live Activity. The names match the PC's push payloads (docs/COMPANION.md, "Push").
struct AgentActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        /// "driving" or "paused".
        var state: String
        /// What the agent is doing at the moment: "acting", "reading", "thinking" or "paused". Older PCs don't send it.
        var phase: String?
        var action: String
        var steps: Int
        /// Unix seconds. A number rather than a Date, because ActivityKit decodes a Date as seconds since 2001.
        var startedAt: Double

        var paused: Bool { state == "paused" }
        /// The phase to show; "paused" whenever the session is paused.
        var currentPhase: String? { paused ? "paused" : phase }
        var startDate: Date { Date(timeIntervalSince1970: startedAt) }
    }

    var pcName: String
}

/// Updates the activities on the phone right away; the PC's next push carries the same state.
func setActivitiesState(_ state: String) async {
    for activity in Activity<AgentActivityAttributes>.activities {
        var content = activity.content.state
        content.state = state
        content.phase = state == "paused" ? "paused" : "thinking"
        await activity.update(ActivityContent(state: content, staleDate: nil))
    }
}

struct TakeOverIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Take Over"
    static var description = IntentDescription("Stops the agent that is using your phone.")

    func perform() async throws -> some IntentResult {
        try await CompanionClient.paired().send("POST", "/v1/agent/takeover", json: [:])
        await setActivitiesState("paused")
        return .result()
    }
}

struct ResumeIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Resume"
    static var description = IntentDescription("Lets the agent continue.")

    func perform() async throws -> some IntentResult {
        try await CompanionClient.paired().send("POST", "/v1/agent/resume", json: [:])
        await setActivitiesState("driving")
        return .result()
    }
}
