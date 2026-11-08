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
                        Text("\(s.steps) steps").font(.caption).monospacedDigit()
                            .contentTransition(.numericText()).foregroundStyle(.secondary)
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
                    Text("\(s.steps)").monospacedDigit().contentTransition(.numericText())
                        .foregroundStyle(look.color(s))
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
        case .idle: return "iphone"
        case .asking: return "hand.raised.fill"
        case .paused: return "pause.fill"
        case .driving:
            switch s.phase {
            case "acting": return "hand.tap.fill"
            case "reading": return "eye.fill"
            case "thinking": return "brain"
            default: return "cursorarrow.rays"
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

/// The state's icon. While driving, a ring runs around it: a Live Activity can't loop an animation, but a
/// timer-driven ProgressView keeps drawing on its own, and it restarts with each update (the PC sends one whenever
/// the phase changes). The icon swaps with a symbol transition.
struct StateIcon: View {
    var state: AgentActivityAttributes.ContentState
    var size: CGFloat

    var body: some View {
        let look = Look(state)
        ZStack {
            if look == .driving {
                let now = Date()
                ProgressView(timerInterval: now...now.addingTimeInterval(3), countsDown: false,
                             label: { EmptyView() }, currentValueLabel: { EmptyView() })
                    .progressViewStyle(.circular)
                    .tint(look.color(state))
            }
            symbol
                .font(.system(size: size * (look == .driving ? 0.45 : 0.7), weight: .semibold))
                .foregroundStyle(look.color(state))
                .contentTransition(.symbolEffect(.replace))
        }
        .frame(width: size, height: size)
    }

    @ViewBuilder private var symbol: some View {
        let image = Image(systemName: Look(state).symbol(state))
        if #available(iOS 18.0, *), Look(state) == .driving {
            // Animates only if the system allows repeating effects in a Live Activity; otherwise it's static.
            image.symbolEffect(.pulse, options: .repeat(.continuous))
        } else {
            image
        }
    }
}

struct IdleView: View {
    var pcName: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "iphone").font(.title3).foregroundStyle(.gray)
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
                    Text("\(state.steps) steps ·").fixedSize().contentTransition(.numericText())
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
                Text("\(state.action) · \(state.steps) steps").font(.caption).foregroundStyle(.secondary).lineLimit(1)
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
