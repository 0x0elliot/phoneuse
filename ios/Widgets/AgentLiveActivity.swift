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
            LockScreenView(state: context.state, pcName: context.attributes.pcName)
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
                    Text("\(s.steps) steps").font(.caption).monospacedDigit().contentTransition(.numericText())
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(s.action).font(.headline).lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack {
                        Text(timerInterval: s.startDate...Date.distantFuture, countsDown: false)
                            .monospacedDigit().foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
                        Spacer()
                        ControlButton(paused: s.paused)
                    }
                }
            } compactLeading: {
                PhaseIcon(state: s)
            } compactTrailing: {
                Text("\(s.steps)").monospacedDigit().contentTransition(.numericText())
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
    case "thinking": return "rays"  // a spinner
    case "reading": return "eye.fill"
    case "acting": return "cursorarrow.click.2"  // a pointer with a tap ripple
    default: return "cursorarrow.rays"  // a PC that doesn't send the phase
    }
}

func phaseColor(_ s: AgentActivityAttributes.ContentState) -> Color {
    switch s.currentPhase {
    case "paused": return .orange
    case "thinking": return .purple
    case "reading": return .mint
    default: return .cyan
    }
}

func phaseName(_ s: AgentActivityAttributes.ContentState) -> String {
    switch s.currentPhase {
    case "paused": return "Paused"
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
                Text(state.paused ? "Paused" : state.action).font(.headline).lineLimit(1)
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
