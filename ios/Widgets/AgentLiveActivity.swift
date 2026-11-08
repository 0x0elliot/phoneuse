import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

@main
struct PhoneUseWidgets: WidgetBundle {
    var body: some Widget {
        AgentLiveActivity()
    }
}

/// One layout for every state: an icon column centered on two lines of text (who has control, then what's
/// happening), and 44 pt capsule buttons under them. The look follows `state` first and, while driving, `phase`.
struct AgentLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: AgentActivityAttributes.self) { context in
            StateCard(state: context.state)
                .padding(16)
                .activityBackgroundTint(Color.black.opacity(0.6))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            let s = context.state
            let look = Look(s)
            return DynamicIsland {
                DynamicIslandExpandedRegion(.bottom) {
                    StateCard(state: s).padding(.horizontal, 4).padding(.bottom, 4)
                }
            } compactLeading: {
                StateIcon(state: s, size: 22)
            } compactTrailing: {
                switch look {
                case .asking:
                    if let deadline = s.deadlineDate {
                        Text(timerInterval: Date()...deadline, countsDown: true)
                            .font(.body.monospacedDigit()).foregroundStyle(.orange).frame(maxWidth: 44)
                    }
                case .driving:
                    if s.steps > 0 {
                        Text("\(s.steps)")
                            .font(.body.monospacedDigit().weight(.semibold))
                            .foregroundStyle(look.color(s))
                            .fixedSize()
                            .frame(minWidth: 18)
                            .contentTransition(.identity)
                            .transaction { $0.animation = nil }
                    }
                case .idle, .paused:
                    EmptyView()
                }
            } minimal: {
                StateIcon(state: s, size: 22)
            }
        }
    }
}

enum Look {
    case idle, asking, driving, paused

    init(_ s: AgentActivityAttributes.ContentState) {
        switch s.state {
        case "idle": self = .idle
        case "asking": self = .asking
        case "paused": self = .paused
        default: self = .driving
        }
    }

    func symbol(_ s: AgentActivityAttributes.ContentState) -> String {
        switch self {
        case .idle: return "person.fill.checkmark"
        case .asking: return "hand.raised.fill"
        case .paused: return "pause.circle.fill"
        case .driving:
            switch s.phase {
            case "acting": return "hand.tap.fill"
            case "reading": return "text.viewfinder"
            default: return "sparkles"
            }
        }
    }

    func color(_ s: AgentActivityAttributes.ContentState) -> Color {
        switch self {
        case .idle: return .gray
        case .asking, .paused: return .orange
        case .driving: return s.phase == "thinking" ? .purple : .blue
        }
    }

    /// Who has control.
    func title(_ s: AgentActivityAttributes.ContentState) -> String {
        switch self {
        case .idle: return "You're in control"
        case .asking: return "Agent requests control"
        case .paused: return "You took over"
        case .driving:
            switch s.phase {
            case "acting": return "Agent is tapping"
            case "reading": return "Agent is reading"
            case "thinking": return "Agent is thinking"
            default: return "Agent is working"
            }
        }
    }

    /// What's happening.
    func detail(_ s: AgentActivityAttributes.ContentState) -> String {
        switch self {
        case .idle: return "Phone Use is mirroring your screen"
        case .asking: return s.action
        case .paused: return "The agent is paused"
        case .driving: return [s.action, s.stepsText].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
        }
    }
}

/// The icon at text weight: SF Symbols, semibold, hierarchical, in the state's tint. While driving, a ring with a gap
/// turns around it: a Live Activity can't loop an animation, and timer-driven views don't animate in the compact
/// Dynamic Island, so the PC sends a refresh every second with `frame` counting up. Each frame turns the ring 45
/// degrees, animated linearly over the second, so the turns join into steady motion. Nothing else animates on an
/// update, so the icon and text stay still while the ring turns.
struct StateIcon: View {
    var state: AgentActivityAttributes.ContentState
    var size: CGFloat

    var body: some View {
        let look = Look(state)
        let frame = state.frame ?? 0
        ZStack {
            if look == .driving {
                Circle()
                    .trim(from: 0, to: 0.72)
                    .stroke(AngularGradient(colors: [look.color(state).opacity(0.05), look.color(state)],
                                            center: .center, startAngle: .degrees(0), endAngle: .degrees(260)),
                            style: StrokeStyle(lineWidth: max(2, size * 0.09), lineCap: .round))
                    .padding(size * 0.06)
                    .rotationEffect(.degrees(Double(frame) * 45))
                    .animation(.linear(duration: 1), value: frame)
            }
            Image(systemName: look.symbol(state))
                .font(.system(size: pointSize(look), weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(look.color(state))
                // Still on every update: only the ring moves with the 1 s frames. A new phase swaps the icon at once.
                .contentTransition(.identity)
                .transition(.identity)
                .transaction { $0.animation = nil }  // no system update animation on the icon
        }
        .frame(width: size, height: size)
    }

    /// About 17 pt in the compact island, 28 pt in the cards; inside the ring while driving.
    private func pointSize(_ look: Look) -> CGFloat {
        if look == .driving { return size * 0.45 }
        return size <= 24 ? 17 : 28
    }
}

/// Every state's expanded and lock-screen layout.
struct StateCard: View {
    var state: AgentActivityAttributes.ContentState

    var body: some View {
        let look = Look(state)
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 12) {
                StateIcon(state: state, size: 44)
                VStack(alignment: .leading, spacing: 2) {
                    title(look).font(.headline.monospacedDigit()).foregroundStyle(.primary).lineLimit(1)
                        .contentTransition(.identity)
                    let detail = look.detail(state)
                    if !detail.isEmpty {
                        Text(detail).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                            .contentTransition(.identity)
                    }
                }
                Spacer(minLength: 0)
            }
            switch look {
            case .idle: EmptyView()
            case .asking: AnswerButtons(requestId: state.requestId ?? "", countdown: state.deadlineDate != nil)
            case .driving: CapsuleButton(title: "Take over", primary: true, intent: TakeOverIntent())
            case .paused: CapsuleButton(title: "Resume", primary: true, intent: ResumeIntent())
            }
        }
    }

    private func title(_ look: Look) -> Text {
        if look == .asking, let deadline = state.deadlineDate {
            return Text("Agent taking control in ") + Text(timerInterval: Date()...deadline, countsDown: true)
        }
        return Text(look.title(state))
    }
}

struct AnswerButtons: View {
    var requestId: String
    /// With a countdown the buttons read Cancel and Allow now; otherwise Deny and Allow.
    var countdown = false

    var body: some View {
        HStack(spacing: 10) {
            CapsuleButton(title: countdown ? "Cancel" : "Deny", primary: false,
                          intent: DenySessionIntent(requestId: requestId))
            CapsuleButton(title: countdown ? "Allow now" : "Allow", primary: true,
                          intent: AllowSessionIntent(requestId: requestId))
        }
    }
}

/// A 44 pt capsule filling its width: primary is orange with black text, secondary gray with white text.
struct CapsuleButton<I: AppIntent>: View {
    var title: String
    var primary: Bool
    var intent: I

    var body: some View {
        Button(intent: intent) {
            Text(title)
                .font(.headline)
                .foregroundStyle(primary ? Color.black : Color.white)
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(Capsule().fill(primary ? Color.orange : Color.white.opacity(0.2)))
        }
        .buttonStyle(.plain)
    }
}
