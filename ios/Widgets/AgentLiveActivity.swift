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

/// One look per state, chosen from `state` first and only then, while driving, from `phase`:
/// idle is a calm grey phone, asking an orange hand with Allow and Deny, driving blue or purple with a word for the
/// phase and a ring that runs while the agent works, and paused an orange pause with Resume.
struct AgentLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: AgentActivityAttributes.self) { context in
            Group {
                switch Look(context.state) {
                case .idle: IdleView(pcName: context.attributes.pcName)
                case .asking: AskingView(state: context.state, pcName: context.attributes.pcName)
                case .driving: DrivingView(state: context.state, pcName: context.attributes.pcName)
                case .paused: PausedView(state: context.state, pcName: context.attributes.pcName)
                }
            }
            .padding()
            .activityBackgroundTint(Color.black.opacity(0.6))
            .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            let s = context.state
            let look = Look(s)
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    if look != .asking { StateIcon(state: s, size: 36) }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    switch look {
                    case .driving, .paused:
                        if let steps = s.stepsText {
                            Text(steps).font(.caption).monospacedDigit()
                                .contentTransition(.identity).foregroundStyle(.secondary)
                        }
                    case .idle:
                        Text(context.attributes.pcName).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    case .asking:
                        EmptyView()
                    }
                }
                DynamicIslandExpandedRegion(.center) {
                    if look != .asking {
                        VStack(spacing: 2) {
                            Text(look.title(s)).font(.caption).foregroundStyle(look.color(s))
                            if look != .idle {
                                Text(s.action).font(.headline).lineLimit(1)
                            }
                        }
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    switch look {
                    case .idle: EmptyView()
                    case .asking: AskingContent(state: s).padding(.horizontal, 4).padding(.bottom, 4)
                    case .driving:
                        HStack {
                            Text(timerInterval: s.startDate...Date.distantFuture, countsDown: false)
                                .monospacedDigit().foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
                            Spacer()
                            TakeOverButton()
                        }
                    case .paused:
                        HStack { Spacer(); ResumeButton() }
                    }
                }
            } compactLeading: {
                StateIcon(state: s, size: 22)
            } compactTrailing: {
                switch look {
                case .idle: EmptyView()
                case .asking:
                    if let deadline = s.deadlineDate {
                        Text(timerInterval: Date()...deadline, countsDown: true)
                            .font(.body.monospacedDigit()).foregroundStyle(.orange).frame(maxWidth: 44)
                    }
                case .driving, .paused:
                    if s.steps > 0 {
                        Text("\(s.steps)").monospacedDigit().contentTransition(.identity)
                            .foregroundStyle(look.color(s))
                            .transaction { $0.animation = nil }
                    }
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

    /// Custom symbols from Shared/Symbols.xcassets (ios/scripts/make_symbols.py).
    func symbol(_ s: AgentActivityAttributes.ContentState) -> String {
        switch self {
        case .idle: return "pu.idle"
        case .asking: return "pu.asking"
        case .paused: return "pu.paused"
        case .driving:
            switch s.phase {
            case "acting": return "pu.tapping"
            case "reading": return "pu.reading"
            default: return "pu.thinking"
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

    func title(_ s: AgentActivityAttributes.ContentState) -> String {
        switch self {
        case .idle: return "You're in control"
        case .asking: return "Agent requests control"
        case .paused: return "You took over"
        case .driving:
            switch s.phase {
            case "acting": return "Tapping"
            case "reading": return "Reading"
            case "thinking": return "Thinking"
            default: return "Agent working"
            }
        }
    }
}

/// The state's icon. While driving, a ring with a gap turns around it: a Live Activity can't loop an animation, and
/// timer-driven views don't animate in the compact Dynamic Island, so the PC sends a refresh every second with
/// `frame` counting up. Each frame turns the ring 45 degrees, animated linearly over the second, so the turns join
/// into steady motion. Nothing else animates on an update, so the icon and text stay still while the ring turns.
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
            Image(look.symbol(state))
                .font(.system(size: size * (look == .driving ? 0.45 : 0.7), weight: .semibold))
                .foregroundStyle(look.color(state))
                // Still on every update: only the ring moves with the 1 s frames. A new phase swaps the icon at once.
                .contentTransition(.identity)
                .transition(.identity)
                .transaction { $0.animation = nil }  // no system update animation on the icon
        }
        .frame(width: size, height: size)
    }
}

struct IdleView: View {
    var pcName: String

    var body: some View {
        HStack(spacing: 10) {
            Image("pu.idle").font(.title3).foregroundStyle(.gray)
            Text("You're in control").font(.subheadline)
            Spacer()
            Text(pcName).font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
    }
}

struct AskingView: View {
    var state: AgentActivityAttributes.ContentState
    var pcName: String

    var body: some View { AskingContent(state: state) }
}

/// A request for control: the hand, one title line (with the countdown inline when there is one), the action under
/// it, and two equal capsule buttons across the full width.
struct AskingContent: View {
    var state: AgentActivityAttributes.ContentState

    var body: some View {
        let deadline = state.deadlineDate
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 12) {
                // Resizable, so the glyph's ink box fills the 28 pt frame and the frame's center is the ink's
                // center, level with the middle of the title and action.
                Image("pu.asking")
                    .resizable()
                    .scaledToFit()
                    .foregroundStyle(.orange)
                    .frame(width: 28, height: 28)
                    .offset(y: 1)  // measured: the text block's visual center sits 1 pt below its frame's
                VStack(alignment: .leading, spacing: 2) {
                    if let deadline {
                        (Text("Agent taking control in ") + Text(timerInterval: Date()...deadline, countsDown: true))
                            .font(.headline.monospacedDigit())
                            .lineLimit(1)
                    } else {
                        Text("Agent requests control").font(.headline).lineLimit(1)
                    }
                    if !state.action.isEmpty {
                        Text(state.action).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
            AnswerButtons(requestId: state.requestId ?? "", countdown: deadline != nil)
        }
    }
}

struct DrivingView: View {
    var state: AgentActivityAttributes.ContentState
    var pcName: String

    var body: some View {
        let look = Look(state)
        HStack(spacing: 12) {
            StateIcon(state: state, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(look.title(state)).font(.caption.weight(.semibold)).foregroundStyle(look.color(state))
                    .contentTransition(.identity)
                Text(state.action).font(.headline).lineLimit(1).contentTransition(.identity)
                HStack(spacing: 4) {
                    if let steps = state.stepsText {
                        Text("\(steps) ·").fixedSize().contentTransition(.identity)
                    }
                    Text(timerInterval: state.startDate...Date.distantFuture, countsDown: false)
                        .frame(width: 72, alignment: .leading)
                }
                .font(.caption).monospacedDigit().foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            TakeOverButton()
        }
    }
}

struct PausedView: View {
    var state: AgentActivityAttributes.ContentState
    var pcName: String

    var body: some View {
        HStack(spacing: 12) {
            StateIcon(state: state, size: 36)
            VStack(alignment: .leading, spacing: 2) {
                Text("You took over").font(.headline)
                Text([state.action, state.stepsText].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            ResumeButton()
        }
    }
}

struct AnswerButtons: View {
    var requestId: String
    /// With a countdown the buttons read Cancel and Allow now; otherwise Deny and Allow.
    var countdown = false

    var body: some View {
        HStack(spacing: 10) {
            Button(intent: DenySessionIntent(requestId: requestId)) {
                Text(countdown ? "Cancel" : "Deny")
                    .font(.headline)
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .background(Capsule().fill(Color.white.opacity(0.2)))
            }
            .buttonStyle(.plain)
            Button(intent: AllowSessionIntent(requestId: requestId)) {
                Text(countdown ? "Allow now" : "Allow")
                    .font(.headline)
                    .foregroundStyle(.black)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .background(Capsule().fill(Color.orange))
            }
            .buttonStyle(.plain)
        }
    }
}

struct TakeOverButton: View {
    var body: some View {
        Button(intent: TakeOverIntent()) { Label("Take over", systemImage: "hand.raised.fill").lineLimit(1).fixedSize() }
            .tint(.orange)
    }
}

struct ResumeButton: View {
    var body: some View {
        Button(intent: ResumeIntent()) { Label("Resume", systemImage: "play.fill").lineLimit(1).fixedSize() }
            .tint(.green)
    }
}
