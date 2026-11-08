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
                    StateIcon(state: s, size: 36)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    switch look {
                    case .driving, .paused:
                        if let steps = s.stepsText {
                            Text(steps).font(.caption).monospacedDigit()
                                .contentTransition(.numericText()).foregroundStyle(.secondary)
                        }
                    case .idle, .asking:
                        Text(context.attributes.pcName).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                DynamicIslandExpandedRegion(.center) {
                    VStack(spacing: 2) {
                        Text(look.title(s)).font(.caption).foregroundStyle(look.color(s))
                        if look != .idle {
                            Text(s.action).font(.headline).lineLimit(1)
                        }
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    switch look {
                    case .idle: EmptyView()
                    case .asking: AnswerButtons(requestId: s.requestId ?? "")
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
                case .asking: Text("Allow?").font(.caption).foregroundStyle(.orange)
                case .driving, .paused:
                    if s.steps > 0 {
                        Text("\(s.steps)").monospacedDigit().contentTransition(.numericText())
                            .foregroundStyle(look.color(s))
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
        case .asking: return "Agent wants to start"
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

/// The state's icon. While driving, a ring fills around it: a Live Activity can't loop an animation, but a
/// timer-driven ProgressView keeps drawing on its own. A pass takes 2.8 s, the PC's refresh interval while
/// driving, and starts when iOS draws the update. It starts at draw time rather than at the PC's updatedAt because
/// iOS may deliver the low-priority refreshes seconds late, and a pass that began at updatedAt would already be full.
/// updatedAt still changes on every refresh, so iOS redraws, and the view is keyed on it so the ring restarts.
struct StateIcon: View {
    static let pass: TimeInterval = 2.8
    var state: AgentActivityAttributes.ContentState
    var size: CGFloat

    var body: some View {
        let look = Look(state)
        ZStack {
            if look == .driving {
                let start = Date()
                ProgressView(timerInterval: start...start.addingTimeInterval(Self.pass), countsDown: false,
                             label: { EmptyView() }, currentValueLabel: { EmptyView() })
                    .progressViewStyle(.circular)
                    .tint(look.color(state).opacity(0.45))
                    .id(state.updatedAt ?? start.timeIntervalSince1970)
                Orbit(since: state.startDate, size: size, color: look.color(state))
            }
            Image(look.symbol(state))
                .font(.system(size: size * (look == .driving ? 0.45 : 0.7), weight: .semibold))
                .foregroundStyle(look.color(state))
                .contentTransition(.symbolEffect(.replace))
        }
        .frame(width: size, height: size)
    }
}

/// A dot that orbits the icon once every 10 s, one step a second, with no pushes: a timer drawn in PUSpin.ttf
/// (ios/scripts/make_spinner_font.py), whose digits are the ten frames, clipped to the seconds' units digit.
struct Orbit: View {
    var since: Date
    var size: CGFloat
    var color: Color

    var body: some View {
        Text(timerInterval: since...Date.distantFuture, countsDown: false)
            .font(.custom("PUSpin", size: size))
            .foregroundStyle(color)
            .lineLimit(1)
            .fixedSize()
            .frame(width: size, height: size, alignment: .trailing)
            .clipped()
            .accessibilityHidden(true)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                StateIcon(state: state, size: 36)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Agent wants to start").font(.caption).foregroundStyle(.orange)
                    Text(state.action).font(.headline).lineLimit(2)
                    Text(pcName).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
            }
            AnswerButtons(requestId: state.requestId ?? "")
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
                    .contentTransition(.opacity)
                Text(state.action).font(.headline).lineLimit(1).contentTransition(.opacity)
                HStack(spacing: 4) {
                    if let steps = state.stepsText {
                        Text("\(steps) ·").fixedSize().contentTransition(.numericText())
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

    var body: some View {
        HStack(spacing: 12) {
            Button(intent: DenySessionIntent(requestId: requestId)) {
                Label("Deny", systemImage: "xmark").lineLimit(1).frame(maxWidth: .infinity)
            }
            .tint(.red)
            Button(intent: AllowSessionIntent(requestId: requestId)) {
                Label("Allow", systemImage: "checkmark").lineLimit(1).frame(maxWidth: .infinity)
            }
            .tint(.green)
        }
        .buttonStyle(.borderedProminent)
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
