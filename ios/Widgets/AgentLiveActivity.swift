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

struct AgentLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: AgentActivityAttributes.self) { context in
            Group {
                if context.state.asking {
                    AskingView(state: context.state, pcName: context.attributes.pcName)
                } else if context.state.idle {
                    IdleView(pcName: context.attributes.pcName)
                } else {
                    LockScreenView(state: context.state, pcName: context.attributes.pcName)
                }
            }
                .padding()
                .activityBackgroundTint(Color.black.opacity(0.6))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            let s = context.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    HStack(spacing: 4) {
                        PhaseIcon(state: s)
                        Text(phaseName(s)).contentTransition(.opacity)
                    }
                    .font(.caption)
                    .foregroundStyle(phaseColor(s))
                }
                DynamicIslandExpandedRegion(.trailing) {
                    if s.asking || s.idle {
                        Text(context.attributes.pcName).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    } else {
                        Text("\(s.steps) steps").font(.caption).monospacedDigit().contentTransition(.numericText())
                    }
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(s.idle ? "You're in control" : s.paused ? "You took over" : s.action)
                        .font(.headline).lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    if s.asking {
                        AnswerButtons(requestId: s.requestId ?? "")
                    } else if !s.idle {
                    HStack {
                        Text(timerInterval: s.startDate...Date.distantFuture, countsDown: false)
                            .monospacedDigit().foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
                        Spacer()
                        ControlButton(paused: s.paused)
                    }
                    }
                }
            } compactLeading: {
                PhaseIcon(state: s)
            } compactTrailing: {
                if s.asking {
                    Text("Allow?").font(.caption).foregroundStyle(phaseColor(s))
                } else if s.idle {
                    EmptyView()
                } else {
                    Text("\(s.steps)").monospacedDigit().contentTransition(.numericText())
                }
            } minimal: {
                PhaseIcon(state: s)
            }
        }
    }
}

/// The icon for what the agent is doing. A Live Activity can't loop an animation, so the icon changes with a
/// symbol transition on each update (the PC sends one every few seconds while the phase changes), and bounces
/// when the step count goes up.
struct PhaseIcon: View {
    var state: AgentActivityAttributes.ContentState

    var body: some View {
        Image(systemName: phaseSymbol(state))
            .foregroundStyle(phaseColor(state))
            .contentTransition(.symbolEffect(.replace))
            .symbolEffect(.bounce, value: state.steps)
    }
}

func phaseSymbol(_ s: AgentActivityAttributes.ContentState) -> String {
    switch s.currentPhase {
    case "paused": return "pause.circle.fill"
    case "asking": return "hand.raised.fill"
    case "idle": return "cursorarrow"  // the PhoneUse glyph, quiet
    case "thinking": return "rays"  // a spinner
    case "reading": return "eye.fill"
    case "acting": return "cursorarrow.click.2"  // a pointer with a tap ripple
    default: return "cursorarrow.rays"  // a PC that doesn't send the phase
    }
}

func phaseColor(_ s: AgentActivityAttributes.ContentState) -> Color {
    switch s.currentPhase {
    case "paused": return .yellow
    case "asking": return .orange
    case "idle": return .secondary
    case "thinking": return .purple
    case "reading": return .mint
    default: return .cyan
    }
}

func phaseName(_ s: AgentActivityAttributes.ContentState) -> String {
    switch s.currentPhase {
    case "paused": return "Paused"
    case "asking": return "Agent wants to start"
    case "idle": return "PhoneUse"
    case "thinking": return "Thinking"
    case "reading": return "Reading"
    case "acting": return "Acting"
    default: return "Agent"
    }
}

struct LockScreenView: View {
    var state: AgentActivityAttributes.ContentState
    var pcName: String

    var body: some View {
        HStack(spacing: 12) {
            PhaseIcon(state: state)
                .font(.title)
                .frame(width: 36)
            VStack(alignment: .leading, spacing: 2) {
                Text(state.paused ? "You took over" : state.action).font(.headline).lineLimit(1)
                    .contentTransition(.opacity)
                HStack(spacing: 4) {
                    Text("\(state.steps) steps ·").fixedSize().contentTransition(.numericText())
                    Text(timerInterval: state.startDate...Date.distantFuture, countsDown: false)
                        .frame(width: 72, alignment: .leading)
                }
                .font(.subheadline).monospacedDigit().foregroundStyle(.secondary).lineLimit(1)
                Text(state.currentPhase == nil || state.paused ? pcName : "\(phaseName(state)) · \(pcName)")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            ControlButton(paused: state.paused)
        }
    }
}

/// No agent: a quiet line while the phone mirrors to the PC.
struct IdleView: View {
    var pcName: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "cursorarrow").font(.title3).foregroundStyle(.secondary)
            Text("You're in control").font(.subheadline)
            Spacer()
            Text(pcName).font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
    }
}

/// A session request: the agent waits for Allow or Deny before its first action.
struct AskingView: View {
    var state: AgentActivityAttributes.ContentState
    var pcName: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                PhaseIcon(state: state)
                    .font(.title)
                    .frame(width: 36)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Agent wants to start").font(.caption).foregroundStyle(.secondary)
                    Text(state.action).font(.headline).lineLimit(2)
                    Text(pcName).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
            }
            AnswerButtons(requestId: state.requestId ?? "")
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

struct ControlButton: View {
    var paused: Bool

    var body: some View {
        if paused {
            Button(intent: ResumeIntent()) { Label("Resume", systemImage: "play.fill").lineLimit(1).fixedSize() }
                .tint(.green)
        } else {
            Button(intent: TakeOverIntent()) { Label("Take over", systemImage: "hand.raised.fill").lineLimit(1).fixedSize() }
                .tint(.orange)
        }
    }
}
