import ActivityKit
import AppIntents
import Foundation

/// The Live Activity. The names match the PC's push payloads (docs/COMPANION.md, "Push").
struct AgentActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        /// "idle", "asking", "driving" or "paused".
        var state: String
        /// What the agent is doing at the moment: "asking", "acting", "reading", "thinking" or "paused". Older PCs
        /// don't send it.
        var phase: String?
        /// While asking: the session request's id, for POST /v1/session/answer.
        var requestId: String?
        var action: String
        var steps: Int
        /// Unix seconds. A number rather than a Date, because ActivityKit decodes a Date as seconds since 2001.
        var startedAt: Double

        var paused: Bool { state == "paused" }
        /// The phase to show; "paused" whenever the session is paused.
        var currentPhase: String? { paused ? "paused" : asking ? "asking" : idle ? "idle" : phase }
        var idle: Bool { state == "idle" }
        var asking: Bool { state == "asking" }
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

/// Answers the session request the activity asks about. The PC then updates the activity (allowed) or ends it
/// (denied); the app changes it at once so the answer shows without waiting for the push.
func answerSessionRequest(_ requestId: String, approve: Bool) async throws {
    try await CompanionClient.paired().send("POST", "/v1/session/answer", json: ["id": requestId, "approve": approve])
    for activity in Activity<AgentActivityAttributes>.activities where activity.content.state.requestId == requestId {
        if approve {
            var c = activity.content.state
            c.state = "driving"
            c.phase = "thinking"
            c.requestId = nil
            await activity.update(ActivityContent(state: c, staleDate: nil))
        } else {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }
}

struct AllowSessionIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Allow Agent"
    static var description = IntentDescription("Lets the agent start using your phone.")
    static var isDiscoverable = false

    @Parameter(title: "Request") var requestId: String

    init() {}
    init(requestId: String) { self.requestId = requestId }

    func perform() async throws -> some IntentResult {
        try await answerSessionRequest(requestId, approve: true)
        return .result()
    }
}

struct DenySessionIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Deny Agent"
    static var description = IntentDescription("Stops the agent from starting.")
    static var isDiscoverable = false

    @Parameter(title: "Request") var requestId: String

    init() {}
    init(requestId: String) { self.requestId = requestId }

    func perform() async throws -> some IntentResult {
        try await answerSessionRequest(requestId, approve: false)
        return .result()
    }
}
